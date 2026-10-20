import { expect, fixture, html } from '@open-wc/testing';
import { renderEvent, renderEventTooltip } from '../src/events/eventRenderers';
import { CampaignSkippedEvent } from '../src/events';

const makeEvent = (reason: string): CampaignSkippedEvent =>
  ({
    type: 'campaign_skipped',
    uuid: 'evt-1',
    created_on: new Date(),
    campaign: { uuid: 'camp-1', name: 'Reminders' },
    point_uuid: 'point-1',
    reason
  }) as unknown as CampaignSkippedEvent;

describe('campaign_skipped', () => {
  it('renders a pill linking to the campaign', async () => {
    const el = await fixture(
      html`<div>${renderEvent(makeEvent('existing_session'), false)}</div>`
    );
    expect(el.textContent).to.contain('Reminders');
    expect(el.textContent).to.contain('Skipped');
    expect(el.querySelector('a').getAttribute('href')).to.equal(
      '/campaign/read/camp-1/'
    );
  });

  it('explains the reason in its tooltip', async () => {
    const inFlow = await fixture(
      html`<div>${renderEventTooltip(makeEvent('existing_session'))}</div>`
    );
    expect(inFlow.textContent).to.contain(
      'Skipped because contact was already in a flow'
    );

    // an unknown reason still gets the timestamp-only tooltip
    const unknown = await fixture(
      html`<div>${renderEventTooltip(makeEvent('other'))}</div>`
    );
    expect(unknown.textContent).to.not.contain('because');
  });
});
