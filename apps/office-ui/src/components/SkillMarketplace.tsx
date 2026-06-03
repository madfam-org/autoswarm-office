'use client';

import { useState, useEffect, useCallback, type FC } from 'react';
import { CloseButton } from '@selva/ui';
import { gameEventBus } from '@/game/PhaserGame';
import { EVENT_CHAT_FOCUS } from '@/lib/constants';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useToast } from '@/hooks/useToast';
import { useMarketplace } from '@/hooks/useMarketplace';
import type {
  MarketplaceEntry,
  MarketplaceEntryDetail,
  MarketplaceSortBy,
} from '@/hooks/useMarketplace';

interface SkillMarketplaceProps {
  open: boolean;
  onClose: () => void;
}

const CATEGORIES = ['All', 'Coding', 'Research', 'Communication', 'Data', 'Other'] as const;
type CategoryFilter = (typeof CATEGORIES)[number];

const SORT_OPTIONS: { value: MarketplaceSortBy; label: string }[] = [
  { value: 'downloads', label: 'Downloads' },
  { value: 'rating', label: 'Rating' },
  { value: 'newest', label: 'Newest' },
];

function StarDisplay({ rating }: { rating: number | null }) {
  if (rating === null) {
    return <span className="font-mono text-[8px] text-slate-500">No ratings</span>;
  }
  const rounded = Math.round(rating);
  const stars: string[] = [];
  for (let i = 1; i <= 5; i++) {
    stars.push(i <= rounded ? '\u2605' : '\u2606');
  }
  return (
    <span className="font-mono text-[10px] text-amber-400" aria-label={`${rating.toFixed(1)} out of 5 stars`}>
      {stars.join('')}
    </span>
  );
}

function StarSelector({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex gap-1" role="radiogroup" aria-label="Rating">
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          onClick={() => onChange(star)}
          className={`font-mono text-[14px] transition-colors ${
            star <= value ? 'text-amber-400' : 'text-slate-600 hover:text-amber-300'
          }`}
          aria-label={`${star} star${star !== 1 ? 's' : ''}`}
          aria-checked={star === value}
          role="radio"
        >
          {star <= value ? '\u2605' : '\u2606'}
        </button>
      ))}
    </div>
  );
}

function CategoryBadge({ category }: { category: string | null }) {
  if (!category) return null;
  const colorMap: Record<string, string> = {
    coding: 'bg-cyan-900/60 text-cyan-300 border-cyan-700',
    research: 'bg-purple-900/60 text-purple-300 border-purple-700',
    communication: 'bg-emerald-900/60 text-emerald-300 border-emerald-700',
    data: 'bg-amber-900/60 text-amber-300 border-amber-700',
  };
  const colors = colorMap[category.toLowerCase()] ?? 'bg-slate-800 text-slate-300 border-slate-600';
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 font-mono text-[7px] uppercase ${colors}`}>
      {category}
    </span>
  );
}

function SkillCard({
  entry,
  onSelect,
  onInstall,
  installing,
}: {
  entry: MarketplaceEntry;
  onSelect: (id: string) => void;
  onInstall: (id: string) => void;
  installing: boolean;
}) {
  return (
    <div
      className="retro-panel cursor-pointer p-3 transition-all duration-150 hover:translate-y-[-1px] hover:shadow-[0_0_8px_rgba(99,102,241,0.3)] animate-fade-in-up"
      onClick={() => onSelect(entry.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(entry.id);
        }
      }}
      aria-label={`View details for ${entry.name}`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="pixel-text text-[9px] text-indigo-400 leading-tight">
          {entry.name}
        </h3>
        <CategoryBadge category={entry.category} />
      </div>

      <p className="mb-1 font-mono text-[8px] text-slate-400">
        by {entry.author} &middot; v{entry.version}
      </p>

      <p className="mb-2 font-mono text-[8px] text-slate-300 line-clamp-2 leading-relaxed">
        {entry.description}
      </p>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StarDisplay rating={entry.avg_rating} />
          <span className="font-mono text-[8px] text-slate-500">
            {entry.downloads} {entry.downloads === 1 ? 'install' : 'installs'}
          </span>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onInstall(entry.id);
          }}
          disabled={installing}
          className="rounded bg-emerald-600 px-2 py-1 font-mono text-[8px] text-white transition-colors hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed retro-btn"
          aria-label={`Install ${entry.name}`}
        >
          {installing ? 'Installing...' : 'Install'}
        </button>
      </div>
    </div>
  );
}

function DetailView({
  detail,
  onBack,
  onInstall,
  onRate,
  onDelete,
  installing,
  submitting,
}: {
  detail: MarketplaceEntryDetail;
  onBack: () => void;
  onInstall: (id: string) => void;
  onRate: (id: string, rating: number, review?: string) => void;
  onDelete: (id: string) => void;
  installing: boolean;
  submitting: boolean;
}) {
  const [ratingValue, setRatingValue] = useState(0);
  const [reviewText, setReviewText] = useState('');

  const handleSubmitReview = useCallback(() => {
    if (ratingValue === 0) return;
    onRate(detail.id, ratingValue, reviewText.trim() || undefined);
    setRatingValue(0);
    setReviewText('');
  }, [detail.id, ratingValue, reviewText, onRate]);

  return (
    <div className="flex flex-col gap-4 animate-fade-in">
      {/* Back button */}
      <button
        onClick={onBack}
        className="self-start font-mono text-[9px] text-slate-400 transition-colors hover:text-white"
        aria-label="Back to skill list"
      >
        &larr; Back to list
      </button>

      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="pixel-text text-[11px] text-indigo-400">{detail.name}</h3>
          <p className="mt-1 font-mono text-[8px] text-slate-400">
            by {detail.author} &middot; v{detail.version}
          </p>
          <div className="mt-1 flex items-center gap-2">
            <StarDisplay rating={detail.avg_rating} />
            <span className="font-mono text-[8px] text-slate-500">
              ({detail.ratings.length} {detail.ratings.length === 1 ? 'review' : 'reviews'})
            </span>
            <CategoryBadge category={detail.category} />
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => onInstall(detail.id)}
            disabled={installing}
            className="rounded bg-emerald-600 px-3 py-1.5 font-mono text-[8px] text-white transition-colors hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed retro-btn"
          >
            {installing ? 'Installing...' : 'Install'}
          </button>
          <button
            onClick={() => onDelete(detail.id)}
            disabled={submitting}
            className="rounded bg-red-700 px-3 py-1.5 font-mono text-[8px] text-white transition-colors hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed retro-btn"
            aria-label={`Delete ${detail.name}`}
          >
            Delete
          </button>
        </div>
      </div>

      {/* Tags */}
      {detail.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {detail.tags.map((tag) => (
            <span
              key={tag}
              className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[7px] text-slate-400 border border-slate-700"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* Description */}
      <div>
        <h4 className="pixel-text mb-1 text-[8px] uppercase text-slate-500">Description</h4>
        <p className="font-mono text-[9px] text-slate-300 leading-relaxed whitespace-pre-wrap">
          {detail.description}
        </p>
      </div>

      {/* Readme */}
      {detail.readme && (
        <div>
          <h4 className="pixel-text mb-1 text-[8px] uppercase text-slate-500">Readme</h4>
          <div className="retro-panel max-h-48 overflow-y-auto p-3">
            <p className="font-mono text-[9px] text-slate-300 leading-relaxed whitespace-pre-wrap">
              {detail.readme}
            </p>
          </div>
        </div>
      )}

      {/* YAML Preview */}
      <div>
        <h4 className="pixel-text mb-1 text-[8px] uppercase text-slate-500">Skill Definition (YAML)</h4>
        <pre className="retro-panel max-h-48 overflow-auto p-3 font-mono text-[8px] text-emerald-300 leading-relaxed">
          {detail.yaml_content}
        </pre>
      </div>

      {/* Rating form */}
      <div className="border-t border-slate-700 pt-3">
        <h4 className="pixel-text mb-2 text-[8px] uppercase text-slate-500">Rate this Skill</h4>
        <div className="flex flex-col gap-2">
          <StarSelector value={ratingValue} onChange={setRatingValue} />
          <textarea
            value={reviewText}
            onChange={(e) => setReviewText(e.target.value)}
            placeholder="Write a review (optional)..."
            rows={2}
            maxLength={500}
            className="w-full resize-none rounded border border-slate-700 bg-slate-800/80 px-2 py-1.5 font-mono text-[9px] text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none"
          />
          <button
            onClick={handleSubmitReview}
            disabled={ratingValue === 0 || submitting}
            className="self-start rounded bg-indigo-600 px-3 py-1 font-mono text-[8px] text-white transition-colors hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed retro-btn"
          >
            Submit Review
          </button>
        </div>
      </div>

      {/* Existing reviews */}
      {detail.ratings.length > 0 && (
        <div>
          <h4 className="pixel-text mb-2 text-[8px] uppercase text-slate-500">Reviews</h4>
          <div className="space-y-2">
            {detail.ratings.map((r, idx) => (
              <div key={`${r.user_id}-${idx}`} className="retro-panel p-2">
                <div className="flex items-center gap-2 mb-1">
                  <StarDisplay rating={r.rating} />
                  <span className="font-mono text-[7px] text-slate-500">
                    {r.user_id.substring(0, 8)}
                  </span>
                </div>
                {r.review && (
                  <p className="font-mono text-[8px] text-slate-300">{r.review}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export const SkillMarketplace: FC<SkillMarketplaceProps> = ({ open, onClose }) => {
  const trapRef = useFocusTrap<HTMLDivElement>(open);
  const { addToast } = useToast();
  const {
    entries,
    entryDetail,
    status,
    error,
    fetchEntries,
    fetchEntry,
    installSkill,
    rateSkill,
    deleteSkill,
    clearDetail,
  } = useMarketplace();

  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<CategoryFilter>('All');
  const [sortBy, setSortBy] = useState<MarketplaceSortBy>('downloads');
  const [installingId, setInstallingId] = useState<string | null>(null);

  // Suppress game input while open
  useEffect(() => {
    if (open) {
      gameEventBus.emit(EVENT_CHAT_FOCUS, true);
      return () => {
        gameEventBus.emit(EVENT_CHAT_FOCUS, false);
      };
    }
  }, [open]);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        if (entryDetail) {
          clearDetail();
        } else {
          onClose();
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose, entryDetail, clearDetail]);

  // Fetch entries on open and when filters change
  useEffect(() => {
    if (!open) return;
    const categoryParam = category === 'All' ? undefined : category.toLowerCase();
    fetchEntries(search || undefined, categoryParam, sortBy);
  }, [open, search, category, sortBy, fetchEntries]);

  // Reset state when closing
  useEffect(() => {
    if (!open) {
      setSearch('');
      setCategory('All');
      setSortBy('downloads');
      clearDetail();
    }
  }, [open, clearDetail]);

  const handleSelectEntry = useCallback(
    (id: string) => {
      fetchEntry(id);
    },
    [fetchEntry],
  );

  const handleInstall = useCallback(
    async (id: string) => {
      setInstallingId(id);
      const ok = await installSkill(id);
      setInstallingId(null);
      if (ok) {
        addToast('Skill installed successfully', 'success');
      } else {
        addToast('Failed to install skill', 'error');
      }
    },
    [installSkill, addToast],
  );

  const handleRate = useCallback(
    async (id: string, rating: number, review?: string) => {
      const ok = await rateSkill(id, rating, review);
      if (ok) {
        addToast('Review submitted', 'success');
        // Refresh detail to show updated rating
        fetchEntry(id);
      } else {
        addToast('Failed to submit review', 'error');
      }
    },
    [rateSkill, addToast, fetchEntry],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      const ok = await deleteSkill(id);
      if (ok) {
        addToast('Skill deleted', 'success');
        clearDetail();
      } else {
        addToast('Failed to delete skill', 'error');
      }
    },
    [deleteSkill, addToast, clearDetail],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-modal animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-label="Skill Marketplace"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-slate-900/95 backdrop-blur-sm" onClick={onClose} />

      {/* Modal container */}
      <div
        ref={trapRef}
        className="absolute inset-4 sm:inset-6 lg:inset-8 retro-panel pixel-border-accent animate-pop-in flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex flex-col gap-3 border-b border-slate-700 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="pixel-text text-[11px] uppercase tracking-wider text-indigo-400">
            Skill Marketplace
          </h2>

          <div className="flex items-center gap-2">
            {/* Search */}
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search skills..."
              className="w-full rounded border border-slate-700 bg-slate-800/80 px-2 py-1 font-mono text-[9px] text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none sm:w-48"
              aria-label="Search skills"
            />

            {/* Sort */}
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as MarketplaceSortBy)}
              className="rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[8px] text-slate-300 focus:border-indigo-500 focus:outline-none"
              aria-label="Sort by"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            {/* Close button */}
            <CloseButton onClick={onClose} label="Close marketplace" shortcut="ESC" />
          </div>
        </div>

        {/* Category filter tabs */}
        <div className="flex gap-1 overflow-x-auto border-b border-slate-800 px-3 py-2">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={`whitespace-nowrap px-2 py-1 font-mono text-[8px] uppercase transition-colors ${
                category === cat
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-white'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {/* Error state */}
          {error && (
            <div className="mb-3 rounded border border-red-500/50 bg-red-900/20 px-3 py-2 font-mono text-[9px] text-red-400">
              {error}
            </div>
          )}

          {/* Loading state */}
          {status === 'loading' && !entryDetail && (
            <div className="flex items-center justify-center py-12">
              <p className="pixel-text animate-pulse text-[10px] text-slate-500">
                Loading...
              </p>
            </div>
          )}

          {/* Detail view */}
          {entryDetail ? (
            <DetailView
              detail={entryDetail}
              onBack={clearDetail}
              onInstall={handleInstall}
              onRate={handleRate}
              onDelete={handleDelete}
              installing={installingId === entryDetail.id}
              submitting={status === 'submitting'}
            />
          ) : status !== 'loading' ? (
            <>
              {/* Empty state */}
              {entries.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12">
                  <p className="pixel-text text-[10px] text-slate-500">No skills found</p>
                  <p className="mt-2 font-mono text-[8px] text-slate-600">
                    {search
                      ? 'Try adjusting your search or filters'
                      : 'No skills have been published yet'}
                  </p>
                </div>
              )}

              {/* Card grid */}
              {entries.length > 0 && (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {entries.map((entry, idx) => (
                    <div key={entry.id} style={{ animationDelay: `${idx * 50}ms` }}>
                      <SkillCard
                        entry={entry}
                        onSelect={handleSelectEntry}
                        onInstall={handleInstall}
                        installing={installingId === entry.id}
                      />
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
};
