"use client";

import { RotateCcw, X } from "lucide-react";
import { useState } from "react";
import { DEFAULT_FILTERS } from "@/types/catalog";
import type { CatalogState, ImageFilter, NoteFilter, OfficialFilter } from "@/types/catalog";
import type { CatalogStateUpdater } from "@/hooks/use-catalog-state";

type CategoryCount = [string, number];

export function FilterPanel({
  open,
  state,
  setState,
  categories,
  onClose,
}: {
  open: boolean;
  state: CatalogState;
  setState: CatalogStateUpdater;
  categories: CategoryCount[];
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(state);
  if (!open) return null;

  const toggleCategory = (name: string) => {
    setDraft((current) => ({
      ...current,
      categories: current.categories.includes(name)
        ? current.categories.filter((category) => category !== name)
        : [...current.categories, name],
    }));
  };

  return (
    <section className="filter-panel" role="dialog" aria-modal="false" aria-labelledby="filter-title">
      <header className="panel-header">
        <div><span className="eyebrow">목록 조건</span><h3 id="filter-title">상품 필터</h3></div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="필터 닫기"><X aria-hidden="true" /></button>
      </header>

      <div className="filter-grid">
        <fieldset className="filter-categories">
          <legend>분류</legend>
          <div className="checkbox-grid">
            {categories.map(([name, count]) => (
              <label key={name}>
                <input type="checkbox" checked={draft.categories.includes(name)} onChange={() => toggleCategory(name)} />
                <span>{name} <small>{count.toLocaleString("ko-KR")}</small></span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend>가격</legend>
          <div className="range-fields">
            <label><span>최저 가격</span><input type="number" min="0" inputMode="numeric" value={draft.priceMin ?? ""} onChange={(event) => setDraft({ ...draft, priceMin: event.target.value ? Number(event.target.value) : undefined })} placeholder="예: 10000" /></label>
            <span aria-hidden="true">–</span>
            <label><span>최고 가격</span><input type="number" min="0" inputMode="numeric" value={draft.priceMax ?? ""} onChange={(event) => setDraft({ ...draft, priceMax: event.target.value ? Number(event.target.value) : undefined })} placeholder="예: 50000" /></label>
          </div>
        </fieldset>

        <div className="filter-selects">
          <label><span>원본 비고</span><select value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value as NoteFilter })}><option value="all">전체</option><option value="with">있음</option><option value="without">없음</option></select></label>
          <label><span>공식 정보</span><select value={draft.official} onChange={(event) => setDraft({ ...draft, official: event.target.value as OfficialFilter })}><option value="all">전체</option><option value="linked">연결됨</option><option value="unlinked">미연결</option></select></label>
          <label><span>공식 이미지</span><select value={draft.image} onChange={(event) => setDraft({ ...draft, image: event.target.value as ImageFilter })}><option value="all">전체</option><option value="with">있음</option><option value="without">없음</option></select></label>
        </div>
      </div>

      <footer className="panel-actions">
        <button type="button" className="secondary-button" onClick={() => setDraft({ ...draft, ...DEFAULT_FILTERS })}><RotateCcw aria-hidden="true" />필터 초기화</button>
        <button type="button" className="primary-button" onClick={() => { setState({
          categories: draft.categories,
          priceMin: draft.priceMin,
          priceMax: draft.priceMax,
          note: draft.note,
          official: draft.official,
          image: draft.image,
          page: 1,
        }); onClose(); }}>필터 적용</button>
      </footer>
    </section>
  );
}
