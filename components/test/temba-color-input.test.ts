import { expect } from '@open-wc/testing';
import { ColorInput } from '../src/form/ColorInput';
import { getComponent } from './utils.test';

const getPicker = async (props: any) => {
  return (await getComponent('temba-color-input', props)) as ColorInput;
};

describe('temba-color-input', () => {
  it('shows the color it holds', async () => {
    const el = await getPicker({
      name: 'color',
      label: 'Color',
      value: '#ff6600'
    });

    expect(el.value).to.equal('#ff6600');
    const swatch = el.shadowRoot.querySelector('.swatch') as HTMLElement;
    expect(swatch.classList.contains('none')).to.equal(false);
    expect(swatch.style.background).to.equal('rgb(255, 102, 0)');
    expect(el.shadowRoot.querySelector('.hex').textContent.trim()).to.equal(
      '#ff6600'
    );
  });

  it('shows no color as a slashed swatch', async () => {
    const el = await getPicker({ name: 'color', placeholder: 'None' });

    expect(el.value).to.equal('');
    expect(
      el.shadowRoot.querySelector('.swatch').classList.contains('none')
    ).to.equal(true);
    expect(el.shadowRoot.querySelector('.hex').textContent.trim()).to.equal(
      'None'
    );
    expect(el.shadowRoot.querySelector('.clear')).to.equal(null);
  });

  it('takes the color picked and fires change', async () => {
    const el = await getPicker({ name: 'color' });
    let changes = 0;
    el.addEventListener('change', () => changes++);

    const input = el.shadowRoot.querySelector('input') as HTMLInputElement;
    input.value = '#123456';
    input.dispatchEvent(new Event('input'));
    await el.updateComplete;

    expect(el.value).to.equal('#123456');
    expect(changes).to.equal(1);

    // the same color again is no change
    input.dispatchEvent(new Event('change'));
    expect(changes).to.equal(1);
  });

  it('can be cleared unless required', async () => {
    const el = await getPicker({ name: 'color', value: '#123456' });
    (el.shadowRoot.querySelector('.clear') as HTMLElement).click();
    await el.updateComplete;

    expect(el.value).to.equal('');
    expect(el.shadowRoot.querySelector('.clear')).to.equal(null);

    const required = await getPicker({
      name: 'color',
      value: '#123456',
      required: true
    });
    expect(required.shadowRoot.querySelector('.clear')).to.equal(null);
  });
});
