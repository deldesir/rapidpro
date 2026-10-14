import { html, TemplateResult } from 'lit-html';
import { css, PropertyValues } from 'lit';
import { msg } from '@lit/localize';
import { property, state } from 'lit/decorators.js';
import { RapidElement } from '../RapidElement';
import { CustomEventType } from '../interfaces';
import { getStore } from '../store/Store';
import { FlowDefinition } from '../store/flow-definition';
import { fetchResults } from '../utils';
import { showLoadErrorDialog } from './utils';
import {
  isHousekeepingOnly,
  labelsFor,
  normalizeChanges,
  RevisionChanges,
  summarizeChanges
} from './revision-summary';

const GROUP_WINDOW_MS = 15 * 60 * 1000;
const MAX_GROUP_LABELS = 3;

const isSystemUser = (user: { email?: string } | null | undefined) =>
  user?.email === 'system';

export interface Revision {
  id: number;
  user: {
    id?: number;
    email?: string;
    username?: string;
    first_name?: string;
    last_name?: string;
    name?: string;
  };
  created_on: string;
  comment?: string;
  changes?: RevisionChanges | null;
}

export class RevisionsWindow extends RapidElement {
  static get styles() {
    return css`
      :host {
        display: contents;
      }
    `;
  }

  @property({ type: String })
  flow = '';

  @property({ type: Boolean })
  hidden = true;

  @property({ type: Boolean })
  saving = false;

  @state()
  private revisions: Revision[] = [];

  @state()
  private viewingRevision: Revision | null = null;

  @state()
  private isLoading = false;

  private preRevertState: {
    definition: FlowDefinition;
    dirtyDate: Date | null;
  } | null = null;
  private browseLanguageCode: string | null = null;
  private fetchRequestId = 0;

  public get isViewingRevision(): boolean {
    return this.viewingRevision !== null;
  }

  public refresh(): void {
    if (!this.hidden) {
      this.fetchRevisions();
    }
  }

  protected updated(changes: PropertyValues): void {
    super.updated(changes);
    if (
      changes.has('hidden') &&
      !this.hidden &&
      changes.get('hidden') === true
    ) {
      this.fetchRevisions();
    }
  }

  public close(): void {
    this.resetScroll();
    if (this.viewingRevision) {
      this.cancelRevisionView();
    }
    this.fireCustomEvent(CustomEventType.RevisionsClosed);
  }

  public render(): TemplateResult {
    return html`
      <temba-floating-window
        id="revisions-window"
        name="revisions"
        header=${msg('Revisions')}
        icon="revisions"
        .width=${340}
        .maxHeight=${500}
        .top=${120}
        color="rgb(142, 94, 167)"
        .saving=${this.saving}
        .hidden=${this.hidden}
        @temba-dialog-hidden=${() => this.close()}
      >
        <div class="localization-window-content">
          <div
            class="revisions-list"
            style="display:flex; flex-direction:column; gap:8px; overflow-y:auto; padding-bottom:10px;"
          >
            ${this.isLoading && !this.revisions.length
              ? html`<temba-loading></temba-loading>`
              : this.revisions.map((rev, index) => {
                  const isCurrent = index === 0;
                  const isSelected = this.viewingRevision?.id === rev.id;
                  const summary = summarizeChanges(rev.changes);
                  return html`
                    <div
                      class="revision-item ${isSelected
                        ? 'selected'
                        : ''} ${isCurrent ? 'current' : ''}"
                      style="padding:8px; border-radius:4px; cursor:pointer; background:${isSelected
                        ? '#f0f6ff'
                        : '#f9fafb'}; border:1px solid ${isSelected
                        ? '#a4cafe'
                        : '#e5e7eb'}; transition: all 0.2s ease;"
                      @click=${() => this.handleRevisionClick(rev)}
                    >
                      ${summary
                        ? html`<div
                            class="revision-summary"
                            style="font-size:13px; color:#111827; line-height:1.3;"
                          >
                            ${summary}
                          </div>`
                        : ''}
                      <div
                        class="revision-meta"
                        style="display:flex; justify-content:space-between; align-items:center; gap:8px; min-height:20px; font-size:11px; color:#6b7280; margin-top:${summary
                          ? '2px'
                          : '0'};"
                      >
                        <div style="flex:1; min-width:0;">
                          <temba-date
                            value=${rev.created_on}
                            display="duration"
                          ></temba-date>
                          · ${this.renderUser(rev.user)}
                        </div>
                        ${isCurrent
                          ? html`<div
                              class="current-label"
                              style="font-size:10px; font-weight:600; text-transform:uppercase; color:#6b7280; background:#e5e7eb; padding:2px 6px; border-radius:10px; letter-spacing:0.5px; flex-shrink:0;"
                            >
                              ${msg('Current')}
                            </div>`
                          : isSelected
                            ? html`<button
                                class="revert-button"
                                style="font-size:10px; font-weight:600; text-transform:uppercase; color:#1e3a8a; background:#a4cafe; padding:2px 6px; border-radius:10px; letter-spacing:0.5px; border:none; cursor:pointer; flex-shrink:0;"
                                @click=${(e: Event) => {
                                  e.stopPropagation();
                                  this.handleRevertClick();
                                }}
                              >
                                ${msg('Revert')}
                              </button>`
                            : html``}
                      </div>

                      ${rev.comment
                        ? html`<div
                            style="font-size:12px; color:#4b5563; margin-top:4px;"
                          >
                            ${rev.comment}
                          </div>`
                        : ''}
                    </div>
                  `;
                })}
          </div>
        </div>
      </temba-floating-window>
    `;
  }

  // --- Private ---

  private renderUser(user: Revision['user']): TemplateResult | string {
    if (isSystemUser(user)) {
      return html`<em>${msg('System update')}</em>`;
    }
    return user?.name || user?.username || '';
  }

  private async fetchRevisions() {
    const requestId = ++this.fetchRequestId;
    this.isLoading = true;
    try {
      const results = await fetchResults(`/flow/revisions/${this.flow}/`);
      if (requestId !== this.fetchRequestId) return;
      this.revisions = this.collapseRevisions(results);
    } catch (e) {
      if (requestId !== this.fetchRequestId) return;
      console.error('Error fetching revisions', e);
    } finally {
      if (requestId === this.fetchRequestId) {
        this.isLoading = false;
      }
    }
  }

  // Lump revisions made in a continuous editing session (within 15 minutes
  // of each other, by the same author) onto their most recent member,
  // merging the tag sets so the summary covers everything that happened in
  // the window. The merged revision is capped at three distinct displayed
  // labels — once a fourth would be introduced we break out into a new row.
  // Revisions by different authors are never merged, since the row would
  // then show one author's change at another's time.
  private collapseRevisions(revisions: Revision[]): Revision[] {
    // The API returns newest-first today; sort defensively so the head/window
    // logic stays correct if that ever changes.
    const newestFirst = [...revisions].sort(
      (a, b) =>
        new Date(b.created_on).getTime() - new Date(a.created_on).getTime()
    );
    // Spec-only revisions are dropped, except the newest revision, which is
    // always kept so the "Current" row is the real current revision and the
    // list is never empty. The rest are normalized so the logic below
    // reasons about real edits only: `changes === null` is the single signal
    // for "no-op" (no known changes) — used both for the time-window bypass
    // and for keeping housekeeping tags out of the merged tag set and label
    // cap.
    const sorted = newestFirst
      .filter((r, i) => i === 0 || !isHousekeepingOnly(r.changes))
      .map((r) => ({
        ...r,
        changes: normalizeChanges(r.changes)
      }));
    const result: Revision[] = [];
    let group: Revision[] = [];
    let groupLabels = new Set<string>();
    let groupHasRealChange = false;

    const flush = () => {
      if (group.length === 0) return;
      const head = group[0];
      const tagSet = new Set<string>();
      let anyKnown = false;
      for (const r of group) {
        if (r.changes) {
          anyKnown = true;
          for (const tag of r.changes.tags || []) tagSet.add(tag);
        }
      }
      result.push({
        ...head,
        changes: anyKnown ? { tags: Array.from(tagSet) } : null
      });
      group = [];
      groupLabels = new Set();
      groupHasRealChange = false;
    };

    for (const rev of sorted) {
      if (group.length === 0) {
        group.push(rev);
        groupLabels = labelsFor(rev.changes);
        groupHasRealChange = !!rev.changes;
        continue;
      }
      const head = group[0];
      const headTime = new Date(head.created_on).getTime();
      const revTime = new Date(rev.created_on).getTime();
      // Compare on whichever identifier the server provides — real data
      // arrives with `email`, while test fixtures use `username`. Falling
      // back through the chain keeps both shapes working.
      const headId = head.user?.email ?? head.user?.username;
      const revId = rev.user?.email ?? rev.user?.username;
      // Two conditions bypass the time window:
      //   1. The incoming rev is itself a no-op — it carries no editorial
      //      intent and should disappear into whichever group it neighbors.
      //   2. The group hasn't accumulated a real change yet — to avoid a
      //      row with no summary, a no-op-only chain reaches forward to
      //      absorb its author's next real edit even if that edit is far
      //      away in time. If the next revision is by someone else, the
      //      no-op row is shown on its own.
      const isNoOp = !rev.changes;
      const bypassWindow = isNoOp || !groupHasRealChange;
      const withinWindow = bypassWindow || headTime - revTime < GROUP_WINDOW_MS;
      // The author check is never bypassed, so a row only ever shows one
      // author's changes. System revisions all share one identity, so they
      // still collapse with each other but never with a user's revisions.
      const sameAuthor = headId === revId;
      const prospective = new Set([...groupLabels, ...labelsFor(rev.changes)]);
      // The label cap is meaningful only when adding a real change to a
      // group that already has one. A no-op contributes zero labels by
      // construction, so it never trips the cap; and a no-op-only chain
      // reaching forward to absorb its first real edit must ignore the cap
      // too, or a sweeping edit (4+ label areas) would still strand the
      // no-op group as an empty-summary row.
      const fitsLabelCap =
        isNoOp || !groupHasRealChange || prospective.size <= MAX_GROUP_LABELS;

      if (withinWindow && sameAuthor && fitsLabelCap) {
        group.push(rev);
        groupLabels = prospective;
        if (!isNoOp) groupHasRealChange = true;
      } else {
        flush();
        group.push(rev);
        groupLabels = labelsFor(rev.changes);
        groupHasRealChange = !!rev.changes;
      }
    }
    flush();
    return result;
  }

  private async handleRevisionClick(revision: Revision) {
    if (this.viewingRevision?.id === revision.id) {
      return;
    }

    const store = getStore().getState();

    if (!this.viewingRevision) {
      this.preRevertState = {
        definition: store.flowDefinition,
        dirtyDate: store.dirtyDate
      };
      this.browseLanguageCode = store.languageCode;
    }

    this.viewingRevision = revision;
    this.isLoading = true;

    this.fireCustomEvent(CustomEventType.RevisionViewed, { revision });

    try {
      await store.fetchRevision(
        `/flow/revisions/${this.flow}`,
        revision.id.toString()
      );
      if (this.browseLanguageCode) {
        store.setLanguageCode(this.browseLanguageCode);
      }
    } catch (e) {
      showLoadErrorDialog(e);
      this.cancelRevisionView();
    } finally {
      this.isLoading = false;
    }
  }

  private cancelRevisionView() {
    const store = getStore().getState();
    const preservedLanguageCode = this.browseLanguageCode || store.languageCode;

    if (this.preRevertState) {
      const currentInfo = store.flowInfo;
      store.setFlowContents({
        definition: this.preRevertState.definition,
        info: currentInfo
      });
      if (this.preRevertState.dirtyDate) {
        store.setDirtyDate(this.preRevertState.dirtyDate);
      }
      if (preservedLanguageCode) {
        store.setLanguageCode(preservedLanguageCode);
      }
    } else {
      store
        .fetchRevision(`/flow/revisions/${this.flow}`)
        .catch(showLoadErrorDialog)
        .finally(() => {
          if (preservedLanguageCode) {
            store.setLanguageCode(preservedLanguageCode);
          }
        });
    }

    this.viewingRevision = null;
    this.preRevertState = null;
    this.browseLanguageCode = null;
    this.fireCustomEvent(CustomEventType.RevisionCancelled);
  }

  private async handleRevertClick() {
    if (!this.viewingRevision || !this.preRevertState) return;

    const store = getStore().getState();
    const preservedLanguageCode = this.browseLanguageCode || store.languageCode;

    const definitionToSave = {
      ...store.flowDefinition,
      revision: this.preRevertState.definition.revision
    };

    this.viewingRevision = null;
    this.preRevertState = null;
    this.browseLanguageCode = null;

    this.fireCustomEvent(CustomEventType.RevisionReverted, {
      definition: definitionToSave,
      languageCode: preservedLanguageCode
    });
  }

  private resetScroll() {
    const win = this.shadowRoot?.querySelector('temba-floating-window');
    const list = win?.shadowRoot?.querySelector('.body');
    if (list) {
      list.scrollTop = 0;
    }
  }
}
