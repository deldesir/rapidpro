import '../temba-modules';
import { fixture, expect } from '@open-wc/testing';
import { useFakeTimers } from 'sinon';
import { StartProgress } from '../src/live/StartProgress';
import {
  mockGET,
  clearMockGets,
  MockSocketProvider,
  waitForCondition
} from './utils.test';
import { setSocketProvider, SocketProvider } from '../src/live/SocketService';

const STATUS_URL = '/api/v2/flow_starts.json';

// a flow start payload as returned by the status endpoint
const start = (overrides: any = {}) => ({
  status: 'S',
  modified_on: new Date().toISOString(),
  progress: { current: 10, total: 100 },
  ...overrides
});

const mockStatus = (results: any[]) => {
  clearMockGets();
  mockGET(/flow_starts\.json/, { results, next: null });
};

const createProgress = async (id = 'start-1'): Promise<StartProgress> => {
  const progress = (await fixture(
    `<temba-start-progress statusEndpoint="${STATUS_URL}"></temba-start-progress>`
  )) as StartProgress;
  // assigning id is what kicks off the first refresh
  progress.id = id;
  await progress.updateComplete;
  // let the fetch promise chain settle
  await new Promise((resolve) => setTimeout(resolve, 0));
  return progress;
};

describe('temba-start-progress', () => {
  afterEach(() => {
    clearMockGets();
  });

  describe('refresh', () => {
    it('pulls progress counts from the status endpoint', async () => {
      mockStatus([start({ progress: { current: 25, total: 200 } })]);
      const progress = await createProgress();
      expect(progress.current).to.equal(25);
      expect(progress.total).to.equal(200);
      expect(progress.refreshes).to.equal(1);
    });

    it('does nothing when the endpoint returns no starts', async () => {
      mockStatus([]);
      const progress = await createProgress();
      expect(progress.refreshes).to.equal(0);
      expect(progress.current).to.equal(undefined);
    });

    it('marks a started run as running', async () => {
      mockStatus([start({ status: 'S' })]);
      const progress = await createProgress();
      expect(progress.running).to.equal(true);
      expect(progress.complete).to.equal(false);
      expect(progress.message).to.equal(null);
    });

    it('shows a preparing message while pending', async () => {
      mockStatus([start({ status: 'P' })]);
      const progress = await createProgress();
      expect(progress.message).to.equal('Preparing to start..');
      expect(progress.running).to.equal(false);
    });

    it('shows a waiting message while queued', async () => {
      mockStatus([start({ status: 'Q' })]);
      const progress = await createProgress();
      expect(progress.message).to.equal('Waiting..');
    });

    for (const status of ['C', 'F', 'I']) {
      it(`treats ${status} as complete`, async () => {
        mockStatus([start({ status, progress: { current: 100, total: 100 } })]);
        const progress = await createProgress();
        expect(progress.complete).to.equal(true);
        expect(progress.running).to.equal(false);
      });
    }

    it('estimates an eta once progress is underway', async () => {
      mockStatus([
        start({
          status: 'S',
          modified_on: new Date(Date.now() - 1000).toISOString(),
          progress: { current: 1000, total: 2000 }
        })
      ]);
      const progress = await createProgress();
      expect(progress.eta).to.be.a('string');
      // the eta is in the near future, not the past
      expect(new Date(progress.eta).getTime()).to.be.greaterThan(
        Date.now() - 1000
      );
    });

    it('skips an eta that is months away', async () => {
      mockStatus([
        start({
          status: 'S',
          modified_on: new Date(Date.now() - 1000).toISOString(),
          progress: { current: 1000, total: 10000000000 }
        })
      ]);
      const progress = await createProgress();
      expect(progress.eta).to.equal(null);
    });

    it('skips the eta when the rate is too low to be meaningful', async () => {
      mockStatus([
        start({
          status: 'S',
          modified_on: new Date(Date.now() - 1000000).toISOString(),
          progress: { current: 1, total: 100 }
        })
      ]);
      const progress = await createProgress();
      expect(progress.eta).to.equal(null);
    });

    it('withdraws an earlier estimate once the rate drops', async () => {
      mockStatus([
        start({
          status: 'S',
          modified_on: new Date(Date.now() - 1000).toISOString(),
          progress: { current: 1000, total: 2000 }
        })
      ]);
      const progress = await createProgress();
      expect(progress.eta).to.be.a('string');

      mockStatus([
        start({
          status: 'S',
          modified_on: new Date(Date.now() - 1000000).toISOString(),
          progress: { current: 1001, total: 2000 }
        })
      ]);
      progress.refresh();
      await waitForCondition(() => progress.refreshes > 1, 60, 50);
      expect(progress.eta).to.equal(null);
    });
  });

  describe('socket', () => {
    const FLOW = '4c9b1a3e-1c7e-4b9e-9d5f-3a2b1c0d9e8f';
    let mockSocket: MockSocketProvider;
    let previousProvider: SocketProvider;

    const createWatching = async (id = 'start-1'): Promise<StartProgress> => {
      mockStatus([
        start({ status: 'S', progress: { current: 10, total: 100 } })
      ]);
      const progress = (await fixture(
        `<temba-start-progress statusEndpoint="${STATUS_URL}" flow="${FLOW}"></temba-start-progress>`
      )) as StartProgress;
      progress.id = id;
      await waitForCondition(() => progress.refreshes > 0, 60, 50);
      return progress;
    };

    beforeEach(() => {
      mockSocket = new MockSocketProvider();
      previousProvider = setSocketProvider(mockSocket);
    });

    afterEach(() => {
      setSocketProvider(previousProvider);
    });

    it('watches the flow socket', async () => {
      const progress = await createWatching();
      const subs = mockSocket.subs.filter((sub) => !sub.unsubscribed);
      expect(subs.map((sub) => sub.channel)).to.deep.equal([`flow:${FLOW}`]);

      progress.remove();
      expect(mockSocket.subs.every((sub) => sub.unsubscribed)).to.equal(true);
    });

    it('applies progress published for its start', async () => {
      const progress = await createWatching('7');

      mockSocket.serverPublish(`flow:${FLOW}`, {
        type: 'start_progress',
        start_id: 7,
        status: 'S',
        progress: { current: 50, total: 100 }
      });
      expect(progress.current).to.equal(50);
      expect(progress.total).to.equal(100);
      expect(progress.running).to.equal(true);

      mockSocket.serverPublish(`flow:${FLOW}`, {
        type: 'start_progress',
        start_id: 7,
        status: 'C',
        progress: { current: 100, total: 100 }
      });
      expect(progress.current).to.equal(100);
      expect(progress.complete).to.equal(true);
      expect(progress.running).to.equal(false);
    });

    it('ignores progress of other starts and other events', async () => {
      const progress = await createWatching('7');

      mockSocket.serverPublish(`flow:${FLOW}`, {
        type: 'start_progress',
        start_id: 8,
        status: 'C',
        progress: { current: 5, total: 5 }
      });
      mockSocket.serverPublish(`flow:${FLOW}`, { type: 'activity' });
      expect(progress.current).to.equal(10);
      expect(progress.complete).to.equal(false);
    });

    it('ignores an update that would take the start backwards', async () => {
      const progress = await createWatching('7');
      const publish = (status: string, current: number) =>
        mockSocket.serverPublish(`flow:${FLOW}`, {
          type: 'start_progress',
          start_id: 7,
          status,
          progress: { current, total: 100 }
        });

      // batches run in parallel, so a batch that loaded the start before it
      // was marked started can still publish queued after it is running
      publish('Q', 25);
      expect(progress.running).to.equal(true);
      expect(progress.message).to.equal(null);
      expect(progress.current).to.equal(25);

      // and a lagging batch can report less progress than we already have
      publish('S', 20);
      expect(progress.current).to.equal(25);

      // once complete, a late running update changes nothing
      publish('C', 100);
      publish('S', 90);
      expect(progress.complete).to.equal(true);
      expect(progress.running).to.equal(false);
      expect(progress.current).to.equal(100);
    });

    it('catches up over http when the socket (re)subscribes', async () => {
      const progress = await createWatching();
      const before = progress.refreshes;

      mockSocket.subs[0].onSubscribed();
      await waitForCondition(() => progress.refreshes > before, 60, 50);
      expect(progress.refreshes).to.equal(before + 1);
    });

    it('does not poll', async () => {
      const progress = await createWatching();
      const after = progress.refreshes;

      await new Promise((resolve) => setTimeout(resolve, 1200));
      expect(progress.refreshes).to.equal(after);
    });
  });

  describe('scheduleRemoval', () => {
    it('removes itself from the DOM after a delay', async () => {
      mockStatus([]);
      const progress = await createProgress();
      const parent = progress.parentElement;
      expect(parent.contains(progress)).to.equal(true);

      const clock = useFakeTimers();
      try {
        progress.scheduleRemoval();
        expect(parent.contains(progress)).to.equal(true);
        clock.tick(5000);
      } finally {
        clock.restore();
      }
      expect(parent.contains(progress)).to.equal(false);
    });
  });

  describe('interrupting', () => {
    it('opens the interrupt dialog', async () => {
      mockStatus([]);
      const progress = await createProgress();
      progress.interruptTitle = 'Stop this start';
      progress.interruptEndpoint = '/flow_start/interrupt/1/';

      const opened: any[] = [];
      const original = (window as any).showModax;
      (window as any).showModax = (title: string, endpoint: string) =>
        opened.push({ title, endpoint });
      try {
        progress.interruptStart();
      } finally {
        (window as any).showModax = original;
      }

      expect(opened).to.deep.equal([
        { title: 'Stop this start', endpoint: '/flow_start/interrupt/1/' }
      ]);
    });

    it('offers an interrupt control only while running', async () => {
      mockStatus([start({ status: 'S' })]);
      const progress = await createProgress();
      progress.interruptTitle = 'Stop';
      progress.interruptEndpoint = '/interrupt/';
      await progress.updateComplete;
      expect(
        progress.shadowRoot.querySelector('temba-icon[name="close"]')
      ).to.not.equal(null);
    });

    it('hides the interrupt control when not running', async () => {
      mockStatus([start({ status: 'C' })]);
      const progress = await createProgress();
      progress.interruptTitle = 'Stop';
      progress.interruptEndpoint = '/interrupt/';
      await progress.updateComplete;
      expect(
        progress.shadowRoot.querySelector('temba-icon[name="close"]')
      ).to.equal(null);
    });

    it('hides the interrupt control with no endpoint configured', async () => {
      mockStatus([start({ status: 'S' })]);
      const progress = await createProgress();
      await progress.updateComplete;
      expect(
        progress.shadowRoot.querySelector('temba-icon[name="close"]')
      ).to.equal(null);
    });
  });
});
