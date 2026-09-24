import { css, html, PropertyValues, TemplateResult } from 'lit';
import { property } from 'lit/decorators.js';
import { repeat } from 'lit/directives/repeat.js';
import { RapidElement } from '../RapidElement';
import { formatCount } from '../utils';

const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];

// each column's strip holds the digits twice, so that a digit can always
// roll onward past 9 to the 0 that follows it, or back past 0 to the 9
// before it, the way an odometer wheel turns
const STRIP = [...DIGITS, ...DIGITS];

/**
 * A count that rolls to its new value like an odometer. Each digit is a
 * column with the digits stacked in it, shifted to show the current one, so
 * a change slides every digit that differs into place rather than swapping
 * the text. All digits roll the same way: onward when the count went up and
 * back when it went down, wrapping through zero as a wheel would. Columns are
 * keyed from the right so the ones, tens, etc. keep their identity as the
 * number grows or shrinks.
 */
export class Counter extends RapidElement {
  static styles = css`
    :host {
      display: inline-flex;
      align-items: baseline;
      font-variant-numeric: tabular-nums;
      line-height: 1;
      vertical-align: baseline;
    }

    .digit {
      display: inline-block;
      height: 1em;
      overflow: hidden;
      vertical-align: top;
    }

    .strip {
      display: flex;
      flex-direction: column;
    }

    .strip > span {
      display: block;
      height: 1em;
      line-height: 1em;
    }
  `;

  @property({ type: Number })
  value = 0;

  // the characters of the formatted value, each keyed by its position from
  // the right so that columns are reused as digits are added or dropped
  private chars: { key: string; char: string }[] = [];

  // where each digit column's strip currently sits, as an index into STRIP
  private positions = new Map<string, number>();

  private previousValue: number = null;

  public willUpdate(changes: PropertyValues): void {
    super.willUpdate(changes);
    if (changes.has('value')) {
      const text = formatCount(this.value);
      this.chars = Array.from(text).map((char, i) => ({
        key: `${text.length - i}`,
        char
      }));
      this.setAttribute('aria-label', text);
    }
  }

  public updated(changes: PropertyValues): void {
    super.updated(changes);
    if (changes.has('value')) {
      const forward =
        this.previousValue === null || this.value >= this.previousValue;
      this.previousValue = this.value;
      this.rollColumns(forward);
    }
  }

  /**
   * Moves every digit column to its new digit, in the direction the count
   * changed. A column that has to pass 0 on the way starts its roll from the
   * same digit in the other half of the strip, so that there is room to keep
   * going in that direction.
   */
  private rollColumns(forward: boolean): void {
    const seen = new Set<string>();

    this.shadowRoot
      .querySelectorAll('.digit')
      .forEach((column: HTMLElement) => {
        const key = column.dataset.key;
        const strip = column.querySelector('.strip') as HTMLElement;
        const digit = DIGITS.indexOf(column.dataset.digit);
        seen.add(key);

        let from = this.positions.get(key);
        if (from === undefined) {
          // a new column shows its digit straight away
          strip.style.transform = `translateY(-${digit}em)`;
          this.positions.set(key, digit);
          return;
        }

        // how far to turn, always 0-9 steps in the count's direction, worked
        // out from the digit the strip shows rather than where it sits on
        // the doubled strip
        const shown = from % 10;
        const steps = forward
          ? (digit - shown + 10) % 10
          : (shown - digit + 10) % 10;
        if (steps === 0) {
          return;
        }

        let to = forward ? from + steps : from - steps;
        if (to >= STRIP.length) {
          from -= 10;
          to -= 10;
        } else if (to < 0) {
          from += 10;
          to += 10;
        }

        this.roll(strip, from, to);
        this.positions.set(key, to);
      });

    for (const key of this.positions.keys()) {
      if (!seen.has(key)) {
        this.positions.delete(key);
      }
    }
  }

  /**
   * Rolls a strip between two positions. The roll is an animation with an
   * explicit start rather than a CSS transition from wherever the strip
   * happens to be, so it always travels exactly the intended way. A strip
   * still mid-roll is finished first, so a burst of changes stays in step.
   * The strip's own style holds the destination, which is what shows once the
   * animation is over.
   */
  private roll(strip: HTMLElement, from: number, to: number): void {
    strip.getAnimations().forEach((animation) => animation.cancel());
    strip.style.transform = `translateY(-${to}em)`;

    const duration = this.getSpeed();
    if (duration > 0) {
      strip.animate(
        [
          { transform: `translateY(-${from}em)` },
          { transform: `translateY(-${to}em)` }
        ],
        { duration, easing: 'cubic-bezier(0.25, 1, 0.5, 1)' }
      );
    }
  }

  // how long a roll takes, from --counter-speed, or no time at all when the
  // viewer has asked for reduced motion
  private getSpeed(): number {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      return 0;
    }
    const speed = getComputedStyle(this)
      .getPropertyValue('--counter-speed')
      .trim();
    if (!speed) {
      return 600;
    }
    const value = parseFloat(speed);
    return speed.endsWith('ms') ? value : value * 1000;
  }

  private renderChar(entry: { key: string; char: string }): TemplateResult {
    if (!DIGITS.includes(entry.char)) {
      return html`<span class="separator">${entry.char}</span>`;
    }

    return html`<span
      class="digit"
      data-key=${entry.key}
      data-digit=${entry.char}
    >
      <span class="strip">
        ${STRIP.map((digit) => html`<span>${digit}</span>`)}
      </span>
    </span>`;
  }

  public render(): TemplateResult {
    return html`${repeat(
      this.chars,
      (entry) => entry.key,
      (entry) => this.renderChar(entry)
    )}`;
  }
}
