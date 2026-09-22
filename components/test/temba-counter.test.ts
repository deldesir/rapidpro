import '../temba-modules';
import { fixture, expect } from '@open-wc/testing';
import { Counter } from '../src/display/Counter';

const createCounter = async (value: number): Promise<Counter> => {
  const counter = (await fixture(
    `<temba-counter value="${value}"></temba-counter>`
  )) as Counter;
  await counter.updateComplete;
  return counter;
};

// where each column's strip sits, as an index into its doubled digit strip
const positions = (counter: Counter): number[] =>
  Array.from(counter.shadowRoot.querySelectorAll('.digit .strip')).map(
    (strip: HTMLElement) =>
      parseInt(strip.style.transform.match(/-?(\d+)em/)[1])
  );

// the digit each column currently shows
const shownDigits = (counter: Counter): string =>
  positions(counter)
    .map((position) => position % 10)
    .join('');

const columns = (counter: Counter): Element[] =>
  Array.from(counter.shadowRoot.querySelectorAll('.digit'));

describe('temba-counter', () => {
  it('shows each digit of the value in its own column', async () => {
    const counter = await createCounter(407);
    expect(columns(counter).length).to.equal(3);
    expect(shownDigits(counter)).to.equal('407');
    expect(counter.getAttribute('aria-label')).to.equal('407');
  });

  it('keeps separators as plain text between the columns', async () => {
    const counter = await createCounter(12345);
    expect(shownDigits(counter)).to.equal('12345');
    expect(counter.getAttribute('aria-label')).to.equal(
      (12345).toLocaleString()
    );
    const separators = counter.shadowRoot.querySelectorAll('.separator');
    expect(separators.length).to.equal((12345).toLocaleString().length - 5);
  });

  it('rolls existing columns to the new digits', async () => {
    const counter = await createCounter(41);
    const before = columns(counter);

    counter.value = 58;
    await counter.updateComplete;

    expect(shownDigits(counter)).to.equal('58');
    // the same two columns were shifted rather than replaced
    expect(columns(counter)).to.deep.equal(before);
  });

  it('keeps the low order columns when the number grows a digit', async () => {
    const counter = await createCounter(99);
    const [tens, ones] = columns(counter);

    counter.value = 105;
    await counter.updateComplete;

    const after = columns(counter);
    expect(after.length).to.equal(3);
    expect(after[1]).to.equal(tens);
    expect(after[2]).to.equal(ones);
    expect(shownDigits(counter)).to.equal('105');
  });

  it('drops the high order columns when the number shrinks', async () => {
    const counter = await createCounter(1200);
    const ones = columns(counter)[3];

    counter.value = 7;
    await counter.updateComplete;

    expect(columns(counter).length).to.equal(1);
    expect(columns(counter)[0]).to.equal(ones);
    expect(shownDigits(counter)).to.equal('7');
  });

  it('rolls forward through zero when a digit wraps upward', async () => {
    const counter = await createCounter(9);
    expect(positions(counter)).to.deep.equal([9]);

    counter.value = 10;
    await counter.updateComplete;

    // the ones column carried on past 9 to the zero that follows it
    expect(positions(counter)).to.deep.equal([1, 10]);
    expect(shownDigits(counter)).to.equal('10');
  });

  it('rolls back through zero when a digit wraps downward', async () => {
    const counter = await createCounter(10);
    expect(positions(counter)).to.deep.equal([1, 0]);

    counter.value = 9;
    await counter.updateComplete;

    // the ones column stepped back from its second zero to the nine before it
    expect(positions(counter)).to.deep.equal([9]);
    expect(shownDigits(counter)).to.equal('9');
  });

  it('starts a roll that wraps from the other half of the strip', async () => {
    // the test browser asks for reduced motion, under which nothing rolls
    const realMatchMedia = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query
    })) as any;
    after(() => (window.matchMedia = realMatchMedia));

    const counter = await createCounter(39);
    counter.value = 40;
    await counter.updateComplete;
    counter.value = 49;
    await counter.updateComplete;
    expect(positions(counter)).to.deep.equal([4, 19]);

    // the ones column is at the end of the strip, so its roll on to 0 is
    // played from the matching 9 in the first half instead
    counter.value = 50;
    await counter.updateComplete;
    expect(positions(counter)).to.deep.equal([5, 10]);

    const ones = counter.shadowRoot.querySelectorAll('.strip')[1];
    const effect = ones.getAnimations()[0].effect as KeyframeEffect;
    const keyframes = effect.getKeyframes();
    expect(keyframes[0].transform).to.equal('translateY(-9em)');
    expect(keyframes[keyframes.length - 1].transform).to.equal(
      'translateY(-10em)'
    );
  });

  it('keeps rolling forward across repeated wraps', async () => {
    const counter = await createCounter(19);
    counter.value = 20;
    await counter.updateComplete;
    expect(positions(counter)).to.deep.equal([2, 10]);

    // from its second zero a further wrap snaps back to the first half
    // of the strip before rolling on, so the strip never runs out
    counter.value = 30;
    await counter.updateComplete;
    expect(positions(counter)).to.deep.equal([3, 10]);
    expect(shownDigits(counter)).to.equal('30');

    counter.value = 31;
    await counter.updateComplete;
    expect(positions(counter)).to.deep.equal([3, 11]);
    expect(shownDigits(counter)).to.equal('31');
  });
});
