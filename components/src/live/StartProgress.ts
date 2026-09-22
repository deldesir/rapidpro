import { css, html, PropertyValueMap, TemplateResult } from 'lit';
import { RapidElement } from '../RapidElement';
import { property } from 'lit/decorators.js';
import { fetchResults, showModax } from '../utils';
import { CustomEventType } from '../interfaces';
import { FlowEvent, RealtimeSubscription, subscribeToFlow } from './Realtime';

// status codes of a flow start, as the status endpoint and the flow socket report them
const STATUS_PENDING = 'P';
const STATUS_QUEUED = 'Q';
const STATUS_STARTED = 'S';
const STATUS_COMPLETED = 'C';
const STATUS_FAILED = 'F';
const STATUS_INTERRUPTED = 'I';

/**
 * Shows the progress of a flow start. The current state is read from the
 * status endpoint when the start is set and whenever the flow's socket is
 * (re)subscribed, and from then on progress arrives over that socket as
 * mailroom finishes each batch of contacts - there is no polling.
 */
export class StartProgress extends RapidElement {
  static styles = css`
    temba-icon[name='close'] {
      cursor: pointer;
      margin: 0 4px;
    }

    temba-icon[name='close']:hover {
      color: var(--color-primary-dark);
    }
  `;
  @property({ type: String })
  id: string;

  /** uuid of the flow being started, whose socket carries the progress */
  @property({ type: String })
  flow: string;

  @property({ type: Number })
  current: number;

  @property({ type: Number })
  total: number;

  /** how many times the status has been fetched */
  @property({ type: Number })
  refreshes: number = 0;

  @property({ type: String })
  eta: string;

  @property({ type: Boolean })
  complete = false;

  @property({ type: Boolean })
  running = false;

  @property({ type: String })
  message: string;

  @property({ type: String })
  statusEndpoint: string;

  @property({ type: String })
  interruptTitle: string;

  @property({ type: String })
  interruptEndpoint: string;

  private subscription: RealtimeSubscription;

  // when the start was seen to be running, which the eta is measured from
  private startedOn: Date;

  private fetching = false;
  private refreshAgain = false;

  public connectedCallback(): void {
    super.connectedCallback();
    this.watchFlow();
  }

  public disconnectedCallback(): void {
    super.disconnectedCallback();
    this.unwatchFlow();
  }

  public updated(
    changes: PropertyValueMap<any> | Map<PropertyKey, unknown>
  ): void {
    super.updated(changes);
    if (changes.has('id')) {
      this.refresh();
    }
    if (changes.has('flow')) {
      this.watchFlow();
    }
  }

  private watchFlow(): void {
    this.unwatchFlow();
    if (!this.flow || !this.isConnected) {
      return;
    }

    this.subscription = subscribeToFlow(
      this.flow,
      (event) => this.handleFlowEvent(event),
      // fires on every (re)subscribe, so catch up on anything published
      // while we weren't listening
      () => this.refresh()
    );
  }

  private unwatchFlow(): void {
    if (this.subscription) {
      this.subscription.unsubscribe();
      this.subscription = null;
    }
  }

  private handleFlowEvent(event: FlowEvent): void {
    if (
      event?.type === 'start_progress' &&
      String(event.start_id) === String(this.id)
    ) {
      this.update_(event.status, event.progress.current, event.progress.total);
    }
  }

  public interruptStart(): void {
    showModax(this.interruptTitle, this.interruptEndpoint);

    // the interrupt is made by the page's modal, which we only hear about
    // when it submits - mailroom won't tell us until its next batch is skipped
    document.addEventListener(CustomEventType.Submitted, () => this.refresh(), {
      once: true
    });
  }

  /**
   * Fetches the start's current state. Since it's also the socket's way of
   * catching up, calls that overlap a fetch in flight are collapsed into one
   * more fetch after it.
   */
  public refresh(): void {
    if (this.fetching) {
      this.refreshAgain = true;
      return;
    }
    this.fetching = true;

    fetchResults(this.statusEndpoint, this.getHeaders())
      .then((data: any) => {
        if (data.length > 0) {
          this.refreshes++;
          const start = data[0];

          // the status endpoint knows when the start began running
          if (start.status === STATUS_STARTED && start.modified_on) {
            this.startedOn = new Date(start.modified_on);
          }

          this.update_(
            start.status,
            start.progress.current,
            start.progress.total
          );
        }
      })
      .finally(() => {
        this.fetching = false;
        if (this.refreshAgain) {
          this.refreshAgain = false;
          this.refresh();
        }
      });
  }

  // applies a new state for the start, from either source
  private update_(status: string, current: number, total: number): void {
    this.current = current;
    this.total = total;

    this.complete =
      status === STATUS_COMPLETED ||
      status === STATUS_FAILED ||
      status === STATUS_INTERRUPTED;

    this.running = status === STATUS_STARTED;

    if (status === STATUS_PENDING) {
      this.message = 'Preparing to start..';
    } else if (status === STATUS_QUEUED) {
      this.message = 'Waiting..';
    } else {
      this.message = null;
    }

    if (this.running) {
      // a socket update only tells us the start is running, not since when
      if (!this.startedOn) {
        this.startedOn = new Date();
      }
      this.updateEta();
    }

    if (this.complete) {
      this.scheduleRemoval();
    }
  }

  private updateEta(): void {
    const elapsed = new Date().getTime() - this.startedOn.getTime();
    const rate = this.current / elapsed;

    // only calculate eta if the rate is actually reasonable
    if (rate > 0.1) {
      const eta = new Date(
        new Date().getTime() + (this.total - this.current) / rate
      );
      // Don't bother with estimates months out
      const nextMonth = new Date();
      nextMonth.setMonth(nextMonth.getMonth() + 2);
      if (eta > nextMonth) {
        this.eta = null;
      } else {
        this.eta = eta.toISOString();
      }
    }
  }

  public scheduleRemoval(): void {
    setTimeout(() => {
      this.remove();
    }, 5000);
  }

  public render(): TemplateResult {
    return html`<temba-progress
      total=${this.total}
      current=${this.current}
      eta=${this.eta}
      message=${this.message}
    >
      ${this.running && this.interruptTitle && this.interruptEndpoint
        ? html`<temba-icon
            name="close"
            @click=${this.interruptStart}
          ></temba-icon>`
        : null}
    </temba-progress>`;
  }
}
