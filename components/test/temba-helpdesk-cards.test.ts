import { assert, expect, oneEvent } from '@open-wc/testing';
import { SinonStub } from 'sinon';
import { Article } from '../src/interfaces';
import {
  groupSections,
  HelpdeskCards,
  matchesQuery,
  moveArticle,
  Section,
  toFullIndex,
  toOrder
} from '../src/list/HelpdeskCards';
import {
  assertScreenshot,
  clearMockGets,
  clearMockPosts,
  getClip,
  getComponent,
  mockGET,
  mockPOST,
  waitForCondition
} from './utils.test';

const TAG = 'temba-helpdesk-cards';

const ENDPOINT = '/api/internal/articles.json';
const SORT_URL = '/article/sort/';
const PUBLISH_URL = '/article/publish/';
const CREATE_URL = '/article/create/';

// getting-started
//   installing (draft)
//   configuring
// flows
//   nodes
const ARTICLES = [
  {
    uuid: 'getting-started',
    title: 'Getting Started',
    description: 'Setting up and finding your way around.',
    status: 'published',
    parent: null,
    depth: 0,
    modified_on: '2026-01-01T00:00:00Z'
  },
  {
    uuid: 'installing',
    title: 'Installing',
    status: 'draft',
    parent: 'getting-started',
    depth: 1,
    modified_on: '2026-01-02T00:00:00Z'
  },
  {
    uuid: 'configuring',
    title: 'Configuring',
    status: 'published',
    parent: 'getting-started',
    depth: 1,
    modified_on: '2026-01-03T00:00:00Z'
  },
  {
    uuid: 'flows',
    title: 'Flows',
    status: 'published',
    parent: null,
    depth: 0,
    modified_on: '2026-01-04T00:00:00Z'
  },
  {
    uuid: 'nodes',
    title: 'Nodes',
    status: 'published',
    parent: 'flows',
    depth: 1,
    modified_on: '2026-01-05T00:00:00Z'
  }
];

const article = (uuid: string, depth = 1, parent: string = null): Article => ({
  uuid,
  title: uuid,
  status: 'published',
  parent,
  depth,
  modified_on: ''
});

// sections as (root, ...articles) tuples so the shape of a case is
// readable at a glance
const sections = (...groups: string[][]): Section[] =>
  groups.map(([root, ...articles]) => ({
    section: article(root, 0),
    articles: articles.map((uuid) => article(uuid, 1, root))
  }));

const shape = (groups: Section[]): string[][] =>
  groups.map((group) => [
    group.section.uuid,
    ...group.articles.map((item) => item.uuid)
  ]);

const getCards = async (attrs: any = {}, width = 800) => {
  const cards = (await getComponent(
    TAG,
    { endpoint: ENDPOINT, 'sort-endpoint': SORT_URL, ...attrs },
    '',
    width
  )) as HelpdeskCards;
  await waitForCondition(() => (cards as any).sections.length > 0);
  await cards.updateComplete;
  return cards;
};

const getCardElements = (cards: HelpdeskCards): HTMLElement[] =>
  Array.from(cards.shadowRoot.querySelectorAll('temba-card'));

const getRows = (cards: HelpdeskCards, cardIndex: number): HTMLElement[] =>
  Array.from(
    getCardElements(cards)[cardIndex].querySelectorAll('.row')
  ) as HTMLElement[];

/** Opens cards (collapsed by default) and waits for the reveal
 * animation to finish so row geometry is real before a drag aims at it. */
const expandAll = async (cards: HelpdeskCards) => {
  getCardElements(cards).forEach((card: any) => (card.collapsed = false));
  await waitForCondition(() => {
    const row = cards.shadowRoot.querySelector('.row');
    return row && row.getBoundingClientRect().height > 0;
  });
  await waitFor(250);
};

// the fetch stub's call history spans the whole run, so each test tracks
// a baseline and only looks at its own posts
let sortBaseline = 0;
let publishBaseline = 0;

const allPostsTo = (url: string): any[] =>
  (window.fetch as SinonStub)
    .getCalls()
    .filter(
      (call) =>
        String(call.args[0]).includes(url) && call.args[1]?.method === 'POST'
    )
    .map((call) => JSON.parse(call.args[1].body));

const getSortPosts = (): any[] => allPostsTo(SORT_URL).slice(sortBaseline);

const getPublishPosts = (): any[] =>
  allPostsTo(PUBLISH_URL).slice(publishBaseline);

/** Drags an article by its handle to a point, the way a user would.
 * The destination is a function because the layout reflows mid-drag -
 * the source slot closes up once the row leaves its card - and a user
 * aims at what they see: the drag moves, then re-aims against the
 * settled layout before dropping. */
const dragArticle = async (
  cards: HelpdeskCards,
  cardIndex: number,
  rowIndex: number,
  to: () => [number, number]
) => {
  const row = getRows(cards, cardIndex)[rowIndex];
  const handle = row.querySelector('.drag-handle');

  // the handle is a nested component, so give it until it has painted a
  // real hit target before aiming the mouse at it
  await waitForCondition(() => {
    const box = handle.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  });

  // a press can land beside the handle while layout is still settling,
  // which would turn the whole drag into a no-op - check the row's own
  // sortable list engaged and re-press if not
  const list = getCardElements(cards)[cardIndex].querySelector(
    'temba-sortable-list'
  ) as any;
  for (let attempt = 0; attempt < 3; attempt++) {
    const bounds = handle.getBoundingClientRect();
    await moveMouse(
      bounds.left + bounds.width / 2,
      bounds.top + bounds.height / 2
    );
    await mouseDown();
    if (list.draggingId) {
      break;
    }
    await mouseUp();
    await waitFor(50);
  }

  await moveMouse(...to());
  // the first move can reflow the stack - re-aim at the live layout
  await moveMouse(...to());
  await mouseUp();
  await cards.updateComplete;
};

describe(TAG, () => {
  beforeEach(async () => {
    clearMockGets();
    clearMockPosts();
    mockGET(/\/api\/internal\/articles\.json/, { results: ARTICLES });
    mockPOST(/\/article\/sort\//, { status: 'ok' });
    mockPOST(/\/article\/publish\//, { status: 'ok' });
    sortBaseline = allPostsTo(SORT_URL).length;
    publishBaseline = allPostsTo(PUBLISH_URL).length;
  });

  describe('groupSections', () => {
    it('files every root as a section and the rows under it as its articles', () => {
      const groups = groupSections(ARTICLES as Article[]);
      expect(shape(groups)).to.deep.equal([
        ['getting-started', 'installing', 'configuring'],
        ['flows', 'nodes']
      ]);
    });

    it('files rows nested past the cap into the section above them', () => {
      // data can predate the depth cap - a grandchild files into the card
      const groups = groupSections([
        article('a', 0),
        article('b', 1, 'a'),
        article('c', 2, 'b')
      ]);
      expect(shape(groups)).to.deep.equal([['a', 'b', 'c']]);
    });

    it('files rows that precede any section into the first one', () => {
      const groups = groupSections([
        article('stray', 1, 'gone'),
        article('a', 0),
        article('b', 1, 'a')
      ]);
      expect(shape(groups)).to.deep.equal([['a', 'stray', 'b']]);
    });
  });

  describe('toOrder', () => {
    it('describes the whole forest, sections at the root', () => {
      expect(toOrder(sections(['a', 'b', 'c'], ['d']))).to.deep.equal([
        { uuid: 'a', parent: null, sort_order: 0 },
        { uuid: 'b', parent: 'a', sort_order: 0 },
        { uuid: 'c', parent: 'a', sort_order: 1 },
        { uuid: 'd', parent: null, sort_order: 1 }
      ]);
    });
  });

  describe('moveArticle', () => {
    it('moves within a card', () => {
      // the index is the slot with b already out: [c, d], slot 2 = the end
      const moved = moveArticle(sections(['a', 'b', 'c', 'd']), 'b', 0, 2);
      expect(shape(moved)).to.deep.equal([['a', 'c', 'd', 'b']]);
    });

    it('puts an article back where it came from unchanged', () => {
      const moved = moveArticle(sections(['a', 'b', 'c']), 'b', 0, 0);
      expect(shape(moved)).to.deep.equal([['a', 'b', 'c']]);
    });

    it('moves between cards and reparents', () => {
      const moved = moveArticle(sections(['a', 'b'], ['c', 'd']), 'b', 1, 1);
      expect(shape(moved)).to.deep.equal([['a'], ['c', 'd', 'b']]);
      expect(moved[1].articles[1].parent).to.equal('c');
    });

    it('clamps an index past the end of the target card', () => {
      const moved = moveArticle(sections(['a', 'b'], ['c']), 'b', 1, 9);
      expect(shape(moved)).to.deep.equal([['a'], ['c', 'b']]);
    });

    it('returns null for an article or section that is not there', () => {
      expect(moveArticle(sections(['a', 'b']), 'x', 0, 0)).to.be.null;
      expect(moveArticle(sections(['a', 'b']), 'b', 4, 0)).to.be.null;
    });
  });

  describe('matchesQuery', () => {
    it('matches part of a title, ignoring case and surrounding space', () => {
      const item = { ...article('x'), title: 'Configuring Channels' };
      expect(matchesQuery(item, 'chan')).to.equal(true);
      expect(matchesQuery(item, '  CONFIG ')).to.equal(true);
      expect(matchesQuery(item, 'flows')).to.equal(false);
      expect(matchesQuery(item, '   ')).to.equal(true);
    });
  });

  describe('toFullIndex', () => {
    const all = ['a', 'b', 'c', 'd', 'e'].map((uuid) => article(uuid));
    const shown = (...uuids: string[]) =>
      all.filter((item) => uuids.includes(item.uuid));

    it('lands before the shown article the slot sits above', () => {
      // b and d showing, c hidden between them
      expect(toFullIndex(all, shown('b', 'd'), 1, 'x')).to.equal(3);
      expect(toFullIndex(all, shown('b', 'd'), 0, 'x')).to.equal(1);
    });

    it('lands just after the last shown article, not at the very end', () => {
      expect(toFullIndex(all, shown('b', 'd'), 2, 'x')).to.equal(4);
    });

    it('lands at the end when nothing is showing', () => {
      expect(toFullIndex(all, [], 0, 'x')).to.equal(5);
    });

    it('counts with the dragged article out', () => {
      // b moves below d, past the hidden c - d sits at 2 once b is out
      expect(toFullIndex(all, shown('b', 'd'), 1, 'b')).to.equal(3);
      expect(toFullIndex(all, shown('b', 'd'), 0, 'd')).to.equal(1);
    });

    it('is the slot itself when nothing is hidden', () => {
      expect(toFullIndex(all, all, 3, 'a')).to.equal(3);
    });
  });

  it('shows what the host puts above the cards, and nothing when it puts nothing', async () => {
    const plain = await getCards();
    assert.isNull(plain.shadowRoot.querySelector('.banner'));

    const cards = (await getComponent(
      TAG,
      { endpoint: ENDPOINT },
      '<div slot="banner" id="site-domain">help.example.com</div>',
      800
    )) as HelpdeskCards;
    await waitForCondition(() => (cards as any).sections.length > 0);
    await cards.updateComplete;

    const banner = cards.shadowRoot.querySelector(
      '.banner slot'
    ) as HTMLSlotElement;
    assert.isOk(banner);
    assert.equal(
      (banner.assignedElements()[0] as HTMLElement).id,
      'site-domain'
    );
  });

  it('renders a card per section with its articles', async () => {
    const cards = await getCards();

    assert.instanceOf(cards, HelpdeskCards);

    const elements = getCardElements(cards);
    expect(elements.length).to.equal(2);
    expect(elements[0].getAttribute('label')).to.equal('Getting Started');
    expect(elements[1].getAttribute('label')).to.equal('Flows');

    // each card says how much is in it, whether or not it's open
    expect(
      elements[0].querySelector('.meta .count').textContent.trim()
    ).to.equal('2 articles');

    // sections arrive shut - a helpdesk is scanned by its sections first
    elements.forEach((card: any) => expect(card.collapsed).to.be.true);

    await expandAll(cards);
    expect(
      getRows(cards, 0).map((row) =>
        row.querySelector('.title').textContent.trim()
      )
    ).to.deep.equal(['Installing', 'Configuring']);

    await assertScreenshot('helpdesk-cards/cards', getClip(cards));
  });

  it('shows the empty message when there are no articles', async () => {
    clearMockGets();
    mockGET(/\/api\/internal\/articles\.json/, { results: [] });

    const cards = (await getComponent(TAG, {
      endpoint: ENDPOINT,
      'empty-message': 'No articles'
    })) as HelpdeskCards;
    await waitForCondition(() => (cards as any).loaded);
    await cards.updateComplete;

    expect(
      cards.shadowRoot.querySelector('.empty-message').textContent.trim()
    ).to.equal('No articles');
  });

  it('offers drag handles and publish switches only with somewhere to post', async () => {
    const cards = await getCards({ 'publish-endpoint': PUBLISH_URL });
    expect(cards.shadowRoot.querySelector('.drag-handle')).to.exist;
    expect(cards.shadowRoot.querySelector('temba-toggle')).to.exist;
    getCardElements(cards).forEach((card) => {
      expect(card.classList.contains('sortable')).to.be.true;
    });

    const readOnly = await getCards({ 'sort-endpoint': '' });
    expect(readOnly.shadowRoot.querySelector('.drag-handle')).to.not.exist;
    expect(readOnly.shadowRoot.querySelector('temba-toggle')).to.not.exist;
    getCardElements(readOnly).forEach((card) => {
      expect(card.classList.contains('sortable')).to.be.false;
    });

    // without the switch, a draft is called out by a pill instead
    const pills = Array.from(readOnly.shadowRoot.querySelectorAll('.pill'));
    expect(pills.length).to.equal(1);
  });

  it('dims a card whose section is a draft', async () => {
    // Flows is unpublished while Nodes under it still is - the section
    // decides; Getting Started holds a draft article but is published
    const drafts = ARTICLES.map((row) =>
      row.uuid === 'flows' ? { ...row, status: 'draft' } : row
    );
    clearMockGets();
    mockGET(/\/api\/internal\/articles\.json/, { results: drafts });

    const cards = await getCards({ 'publish-endpoint': PUBLISH_URL });
    const [gettingStarted, flows] = getCardElements(cards);
    expect(gettingStarted.hasAttribute('unpublished')).to.be.false;
    expect(flows.hasAttribute('unpublished')).to.be.true;

    // publishing the section itself brings the card back straight away,
    // and it stays back once the tree is reconciled against the server -
    // which now agrees
    clearMockGets();
    mockGET(/\/api\/internal\/articles\.json/, { results: ARTICLES });
    const toggle = flows.querySelector('.section-actions temba-toggle') as any;
    toggle.click();
    await waitForCondition(() => getPublishPosts().length > 0);
    await cards.updateComplete;
    expect(flows.hasAttribute('unpublished')).to.be.false;
    await waitForCondition(
      () => !getCardElements(cards)[1].hasAttribute('unpublished')
    );
  });

  it('dims a draft article row', async () => {
    const cards = await getCards({ 'publish-endpoint': PUBLISH_URL });
    await expandAll(cards);
    const [installing, configuring] = getRows(cards, 0);
    expect(installing.classList.contains('draft')).to.be.true;
    expect(configuring.classList.contains('draft')).to.be.false;
  });

  it('keeps a dragged card and row in its own root', async () => {
    // ghosts appended to the body would fall outside this stylesheet
    const cards = await getCards();
    const stack = cards.shadowRoot.querySelector('.stack') as any;
    expect(stack.ghostContainer).to.equal(cards.shadowRoot);
    const rows = cards.shadowRoot.querySelector('.rows') as any;
    expect(rows.ghostContainer).to.equal(cards.shadowRoot);
  });

  it('shows a section description under its title in the card header', async () => {
    const cards = await getCards();
    const [gettingStarted, flows] = getCardElements(cards);
    const description = gettingStarted.querySelector('.description');
    expect(description.textContent.trim()).to.equal(
      'Setting up and finding your way around.'
    );
    expect(description.closest('[slot]').getAttribute('slot')).to.equal(
      'description'
    );
    expect(flows.querySelector('.description')).to.not.exist;
  });

  it('jumps to a section from the overview, opening its card', async () => {
    // wide enough for the overview to stand beside the outline
    const cards = await getCards({}, 1200);
    const overview = cards.shadowRoot.querySelector('.overview');
    expect(getComputedStyle(overview).display).to.equal('block');

    // each one a button, so it's announced and activated as one
    const items = Array.from(
      overview.querySelectorAll('button.toc-item')
    ) as HTMLElement[];
    expect(
      items.map((item) => item.querySelector('.toc-title').textContent.trim())
    ).to.deep.equal(['Getting Started', 'Flows']);

    await assertScreenshot('helpdesk-cards/overview', getClip(cards));

    const flows = getCardElements(cards)[1] as any;
    expect(flows.collapsed).to.be.true;
    items[1].click();
    expect(flows.collapsed).to.be.false;
    expect(flows.classList.contains('flash')).to.be.true;
  });

  it('opens and shuts every card from the overview', async () => {
    const cards = await getCards({}, 1200);
    const button = cards.shadowRoot.querySelector('.expand-all') as HTMLElement;
    expect(button.textContent.trim()).to.equal('Expand all');

    button.click();
    await cards.updateComplete;
    getCardElements(cards).forEach(
      (card: any) => expect(card.collapsed).to.be.false
    );
    expect(button.textContent.trim()).to.equal('Collapse all');

    button.click();
    await cards.updateComplete;
    getCardElements(cards).forEach(
      (card: any) => expect(card.collapsed).to.be.true
    );
  });

  it('keeps the overview out of a narrow page', async () => {
    const cards = await getCards();
    const overview = cards.shadowRoot.querySelector('.overview');
    expect(getComputedStyle(overview).display).to.equal('none');
  });

  it('offers to add an article only with somewhere to create one', async () => {
    const cards = await getCards();
    expect(cards.shadowRoot.querySelector('.section-add')).to.not.exist;

    const creating = await getCards({ 'create-endpoint': CREATE_URL });
    const adds = Array.from(
      creating.shadowRoot.querySelectorAll('.section-add')
    );
    expect(adds.length).to.equal(2);

    // the host makes the article, we say which section it goes in
    const requested = oneEvent(creating, 'temba-article-add-requested', false);
    (adds[1] as HTMLElement).click();
    const event = await requested;
    expect(event.detail.section.uuid).to.equal('flows');

    // and asking doesn't collapse the card
    expect((getCardElements(creating)[1] as any).collapsed).to.be.true;
  });

  it('offers an empty section its first article', async () => {
    // Flows with nothing filed under it yet
    clearMockGets();
    mockGET(/\/api\/internal\/articles\.json/, {
      results: ARTICLES.filter((row) => row.uuid !== 'nodes')
    });

    const cards = await getCards();
    await expandAll(cards);
    const flows = getCardElements(cards)[1];
    expect(flows.querySelector('.empty-note')).to.exist;
    expect(flows.querySelector('.empty-add')).to.not.exist;

    const creating = await getCards({ 'create-endpoint': CREATE_URL });
    const add = getCardElements(creating)[1].querySelector(
      '.empty-add'
    ) as HTMLElement;
    expect(add).to.exist;

    let requested = oneEvent(creating, 'temba-article-add-requested', false);
    add.click();
    expect((await requested).detail.section.uuid).to.equal('flows');

    // and from the keyboard, by either key a button answers to
    for (const key of ['Enter', ' ']) {
      requested = oneEvent(creating, 'temba-article-add-requested', false);
      add.dispatchEvent(new KeyboardEvent('keydown', { key }));
      expect((await requested).detail.section.uuid).to.equal('flows');
    }
  });

  it('opens an article from its row', async () => {
    const cards = await getCards();
    await expandAll(cards);

    let clicked = null;
    cards.addEventListener('temba-row-click', (event: CustomEvent) => {
      clicked = event.detail.item;
    });

    getRows(cards, 0)[0].click();
    expect(clicked.uuid).to.equal('installing');
  });

  it('opens the section itself from its edit affordance', async () => {
    const cards = await getCards();

    let clicked = null;
    cards.addEventListener('temba-row-click', (event: CustomEvent) => {
      clicked = event.detail.item;
    });

    const edit = getCardElements(cards)[0].querySelector(
      '.section-edit'
    ) as HTMLElement;
    edit.click();
    expect(clicked.uuid).to.equal('getting-started');

    // and using it doesn't toggle the card open
    expect((getCardElements(cards)[0] as any).collapsed).to.be.true;
  });

  it('posts a publish change and reconciles', async () => {
    const cards = await getCards({ 'publish-endpoint': PUBLISH_URL });
    await expandAll(cards);

    // Installing is the draft, so its switch is the one to turn on
    const toggle = getRows(cards, 0)[0].querySelector('temba-toggle') as any;
    toggle.click();

    await waitForCondition(() => getPublishPosts().length > 0);
    expect(getPublishPosts()[0]).to.deep.equal({
      uuid: 'installing',
      status: 'published'
    });
  });

  it('drags an article within its card', async () => {
    const cards = await getCards();
    await expandAll(cards);

    // drop Installing below Configuring
    await dragArticle(cards, 0, 0, () => {
      const below = getRows(cards, 0)[1].getBoundingClientRect();
      return [below.left + 40, below.bottom + 2];
    });

    await waitForCondition(() => getSortPosts().length > 0);
    expect(getSortPosts()[0]).to.deep.equal([
      { uuid: 'getting-started', parent: null, sort_order: 0 },
      { uuid: 'configuring', parent: 'getting-started', sort_order: 0 },
      { uuid: 'installing', parent: 'getting-started', sort_order: 1 },
      { uuid: 'flows', parent: null, sort_order: 1 },
      { uuid: 'nodes', parent: 'flows', sort_order: 0 }
    ]);
  });

  it('drags an article into another card', async () => {
    const cards = await getCards();
    await expandAll(cards);

    // drop Installing above Nodes in the Flows card
    await dragArticle(cards, 0, 0, () => {
      const target = getRows(cards, 1)[0].getBoundingClientRect();
      return [target.left + 40, target.top + 2];
    });

    await waitForCondition(() => getSortPosts().length > 0);
    expect(getSortPosts()[0]).to.deep.equal([
      { uuid: 'getting-started', parent: null, sort_order: 0 },
      { uuid: 'configuring', parent: 'getting-started', sort_order: 0 },
      { uuid: 'flows', parent: null, sort_order: 1 },
      { uuid: 'installing', parent: 'flows', sort_order: 0 },
      { uuid: 'nodes', parent: 'flows', sort_order: 1 }
    ]);
  });

  it('drops into a collapsed card at the end', async () => {
    const cards = await getCards();

    // only the source card is open - the target stays shut
    const source = getCardElements(cards)[0] as any;
    source.collapsed = false;
    await waitForCondition(() => {
      const row = getRows(cards, 0)[0];
      return row && row.getBoundingClientRect().height > 0;
    });
    await waitFor(250);

    await dragArticle(cards, 0, 0, () => {
      const target = getCardElements(cards)[1].getBoundingClientRect();
      return [target.left + 40, target.bottom - 2];
    });

    await waitForCondition(() => getSortPosts().length > 0);
    expect(getSortPosts()[0]).to.deep.equal([
      { uuid: 'getting-started', parent: null, sort_order: 0 },
      { uuid: 'configuring', parent: 'getting-started', sort_order: 0 },
      { uuid: 'flows', parent: null, sort_order: 1 },
      { uuid: 'nodes', parent: 'flows', sort_order: 0 },
      { uuid: 'installing', parent: 'flows', sort_order: 1 }
    ]);
  });

  it('posts nothing for a drop outside any card', async () => {
    const cards = await getCards();
    await expandAll(cards);

    const host = cards.getBoundingClientRect();
    await dragArticle(cards, 0, 0, () => [host.left + 10, host.bottom + 200]);

    expect(getSortPosts()).to.deep.equal([]);
  });

  it('posts nothing for a drop back into the same slot', async () => {
    const cards = await getCards();
    await expandAll(cards);

    // measured before the drag - internally the slot is held open by the
    // list's own placeholder, so the layout holds still
    const row = getRows(cards, 0)[0].getBoundingClientRect();
    await dragArticle(cards, 0, 0, () => [row.left + 40, row.top + 2]);

    expect(getSortPosts()).to.deep.equal([]);
  });

  it('drags a card by its header to reorder sections', async () => {
    const cards = await getCards();

    const header = getCardElements(cards)[0].shadowRoot.querySelector(
      '.card-header'
    ) as HTMLElement;
    const from = header.getBoundingClientRect();
    const below = getCardElements(cards)[1].getBoundingClientRect();

    await moveMouse(from.left + from.width / 2, from.top + from.height / 2);
    await mouseDown();
    await moveMouse(from.left + from.width / 2, below.bottom + 10);
    await mouseUp();
    await cards.updateComplete;

    await waitForCondition(() => getSortPosts().length > 0);
    expect(getSortPosts()[0]).to.deep.equal([
      { uuid: 'flows', parent: null, sort_order: 0 },
      { uuid: 'nodes', parent: 'flows', sort_order: 0 },
      { uuid: 'getting-started', parent: null, sort_order: 1 },
      { uuid: 'installing', parent: 'getting-started', sort_order: 0 },
      { uuid: 'configuring', parent: 'getting-started', sort_order: 1 }
    ]);
  });

  describe('search', () => {
    const search = async (cards: HelpdeskCards, query: string) => {
      const input = cards.shadowRoot.querySelector(
        '.searchbar input'
      ) as HTMLInputElement;
      input.value = query;
      input.dispatchEvent(new InputEvent('input'));
      await cards.updateComplete;
      // the cards open and shut to the search, then settle
      await waitFor(250);
    };

    const rowIds = (cards: HelpdeskCards, cardIndex: number) =>
      getRows(cards, cardIndex).map((row) => row.id);

    it('narrows each card to its matching articles', async () => {
      const cards = await getCards();
      await search(cards, 'conf');

      const [gettingStarted, flows] = getCardElements(cards) as any[];
      expect(rowIds(cards, 0)).to.deep.equal(['configuring']);
      expect(gettingStarted.collapsed).to.equal(false);
      expect(gettingStarted.hasAttribute('no-match')).to.equal(false);

      // the card without a match stays as a place to drop, shut and dimmed
      expect(flows.collapsed).to.equal(true);
      expect(flows.hasAttribute('no-match')).to.equal(true);

      // the row keeps its real position in its section
      const row = getRows(cards, 0)[0];
      expect(row.style.getPropertyValue('counter-set')).to.equal('article 2');
      expect(row.querySelector('mark').textContent).to.equal('Conf');

      expect(
        cards.shadowRoot.querySelector('.search-count').textContent.trim()
      ).to.equal('1 match');

      await assertScreenshot('helpdesk-cards/search', getClip(cards));
    });

    it("shows a section's every article when its title matches", async () => {
      const cards = await getCards();
      await search(cards, 'getting');

      expect(rowIds(cards, 0)).to.deep.equal(['installing', 'configuring']);
    });

    it('says when nothing matches', async () => {
      const cards = await getCards();
      await search(cards, 'zzz');

      expect(
        cards.shadowRoot.querySelector('.no-matches').textContent
      ).to.contain('No articles match "zzz"');
      getCardElements(cards).forEach((card) =>
        expect(card.hasAttribute('no-match')).to.equal(true)
      );
    });

    it('puts the cards back the way they were when cleared', async () => {
      const cards = await getCards();
      const [first, second] = getCardElements(cards) as any[];
      second.setCollapsed(false);
      await waitFor(250);

      await search(cards, 'install');
      expect(first.collapsed).to.equal(false);
      expect(second.collapsed).to.equal(true);

      const input = cards.shadowRoot.querySelector(
        '.searchbar input'
      ) as HTMLInputElement;
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      await cards.updateComplete;
      await waitFor(250);

      expect(input.value).to.equal('');
      expect(first.collapsed).to.equal(true);
      expect(second.collapsed).to.equal(false);
      expect(rowIds(cards, 0)).to.deep.equal(['installing', 'configuring']);
    });

    it('drags a matching article into a card without a match', async () => {
      const cards = await getCards();
      await search(cards, 'conf');

      // Flows is shut by the search, so the drop files at its end
      await dragArticle(cards, 0, 0, () => {
        const target = getCardElements(cards)[1].getBoundingClientRect();
        return [target.left + 40, target.bottom - 2];
      });

      await waitForCondition(() => getSortPosts().length > 0);
      expect(getSortPosts()[0]).to.deep.equal([
        { uuid: 'getting-started', parent: null, sort_order: 0 },
        { uuid: 'installing', parent: 'getting-started', sort_order: 0 },
        { uuid: 'flows', parent: null, sort_order: 1 },
        { uuid: 'nodes', parent: 'flows', sort_order: 0 },
        { uuid: 'configuring', parent: 'flows', sort_order: 1 }
      ]);
    });

    it('drops amongst the shown articles of another card', async () => {
      const cards = await getCards();
      // Configuring alone in its card, and Flows matching by its title
      await search(cards, 'o');
      expect(rowIds(cards, 0)).to.deep.equal(['configuring']);
      expect(rowIds(cards, 1)).to.deep.equal(['nodes']);

      // Configuring above Nodes
      await dragArticle(cards, 0, 0, () => {
        const target = getRows(cards, 1)[0].getBoundingClientRect();
        return [target.left + 40, target.top + 2];
      });

      await waitForCondition(() => getSortPosts().length > 0);
      expect(getSortPosts()[0]).to.deep.equal([
        { uuid: 'getting-started', parent: null, sort_order: 0 },
        { uuid: 'installing', parent: 'getting-started', sort_order: 0 },
        { uuid: 'flows', parent: null, sort_order: 1 },
        { uuid: 'configuring', parent: 'flows', sort_order: 0 },
        { uuid: 'nodes', parent: 'flows', sort_order: 1 }
      ]);
    });
  });
});
