import '../temba-modules';
import { fixture, expect } from '@open-wc/testing';
import { ProgressBar } from '../src/display/ProgressBar';
import { assertScreenshot, getClip } from './utils.test';

const createProgress = async (attrs: string): Promise<ProgressBar> => {
  const progress = (await fixture(
    `<temba-progress total="100" current="25" ${attrs}></temba-progress>`
  )) as ProgressBar;
  await progress.updateComplete;
  return progress;
};

const inMinutes = (minutes: number) =>
  new Date(Date.now() + minutes * 60 * 1000).toISOString();

describe('temba-progress', () => {
  it('keeps its message at the right end of the bar', async () => {
    const progress = (await fixture(
      `<temba-progress total="100" current="0" message="Waiting.." style="width: 400px"></temba-progress>`
    )) as ProgressBar;
    await progress.updateComplete;
    await assertScreenshot('progress/message', getClip(progress));
  });

  it('shows how far along it is', async () => {
    const progress = (await fixture(
      `<temba-progress total="100" current="34" style="width: 400px"></temba-progress>`
    )) as ProgressBar;
    await progress.updateComplete;
    await assertScreenshot('progress/running', getClip(progress));
  });

  it('shows the percentage without an estimate', async () => {
    const progress = await createProgress('');
    expect(progress.showEstimatedCompletion).to.equal(false);
    expect(progress.shadowRoot.querySelector('.etc').textContent).to.contain(
      '25%'
    );
  });

  it('shows a countdown for an estimate that is far enough off', async () => {
    const progress = await createProgress(`eta="${inMinutes(30)}"`);
    expect(progress.showEstimatedCompletion).to.equal(true);
    expect(progress.shadowRoot.querySelector('.etc temba-date')).to.not.equal(
      null
    );
  });

  it('keeps to the percentage for an estimate under five minutes', async () => {
    const progress = await createProgress(`eta="${inMinutes(4)}"`);
    expect(progress.showEstimatedCompletion).to.equal(false);
    expect(progress.shadowRoot.querySelector('.etc temba-date')).to.equal(null);
    expect(progress.shadowRoot.querySelector('.etc').textContent).to.contain(
      '25%'
    );
  });

  it('ignores an estimate that has already passed', async () => {
    const progress = await createProgress(`eta="${inMinutes(-1)}"`);
    expect(progress.showEstimatedCompletion).to.equal(false);
  });
});
