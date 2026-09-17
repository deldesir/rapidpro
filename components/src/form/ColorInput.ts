import { TemplateResult, html, css } from 'lit';
import { property } from 'lit/decorators.js';
import { FieldElement } from './FieldElement';
import { Icon } from '../Icons';

/**
 * A color field: a swatch showing the color it holds, which opens the browser's own picker when clicked, with the
 * hex value alongside. An optional field can be cleared back to no color at all, which it holds as an empty value.
 */
export class ColorInput extends FieldElement {
  static get styles() {
    return css`
      ${super.styles}

      :host {
        display: block;
      }

      .color-container {
        display: flex;
        align-items: center;
        gap: 10px;
        border-radius: var(--curvature-widget);
        background: var(--color-widget-bg);
        border: 1px solid var(--color-widget-border);
        box-shadow: var(--widget-box-shadow);
        min-height: var(--input-h);
        padding: 0 10px;
        cursor: pointer;
        transition: all ease-in-out var(--transition-speed);
      }

      .color-container:focus-within {
        border-color: var(--color-focus);
        background: var(--color-widget-bg-focused);
        box-shadow: var(--widget-box-shadow-focused);
      }

      /* the swatch is the color input itself wearing swatch clothes, so the browser's picker opens where it is */
      .swatch {
        position: relative;
        flex-shrink: 0;
        width: 22px;
        height: 22px;
        border-radius: 5px;
        border: 1px solid var(--color-widget-border);
        box-sizing: border-box;
      }

      /* no color yet - blank with a slash through it */
      .swatch.none {
        background:
          linear-gradient(
            to top right,
            transparent calc(50% - 1px),
            #e05252 calc(50% - 1px),
            #e05252 calc(50% + 1px),
            transparent calc(50% + 1px)
          ),
          var(--color-widget-bg);
      }

      .swatch input[type='color'] {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        border: none;
        padding: 0;
        opacity: 0;
        cursor: pointer;
      }

      .hex {
        flex-grow: 1;
        font-family: var(--font-family);
        font-size: var(--temba-textinput-font-size, 14px);
        color: var(--color-widget-text);
      }

      .hex.placeholder {
        color: var(--color-placeholder, #aaa);
      }

      .clear {
        display: flex;
        align-items: center;
        color: var(--color-text-help);
        cursor: pointer;
      }

      .clear:hover {
        color: var(--color-text-dark);
      }
    `;
  }

  /** a required color can't be cleared - only picked */
  @property({ type: Boolean })
  required = false;

  @property({ type: String })
  placeholder = '';

  private handleInput(evt: Event): void {
    this.setColor((evt.target as HTMLInputElement).value);
  }

  private handleClear(evt: Event): void {
    evt.stopPropagation();
    this.setColor('');
  }

  private setColor(hex: string): void {
    if (hex === this.value) {
      return;
    }
    this.value = hex;
    this.dispatchEvent(new Event('change', { bubbles: true }));
  }

  protected renderWidget(): TemplateResult {
    const hex = this.value || '';

    return html`
      <div class="color-container">
        <div
          class="swatch ${hex ? '' : 'none'}"
          style=${hex ? `background:${hex}` : ''}
        >
          <input
            type="color"
            .value=${hex || '#ffffff'}
            ?disabled=${this.disabled}
            @input=${this.handleInput}
            @change=${this.handleInput}
          />
        </div>
        <div class="hex ${hex ? '' : 'placeholder'}">
          ${hex || this.placeholder}
        </div>
        ${hex && !this.required && !this.disabled
          ? html`
              <div class="clear" title="Clear" @click=${this.handleClear}>
                <temba-icon name=${Icon.delete_small}></temba-icon>
              </div>
            `
          : null}
      </div>
    `;
  }
}
