"use client";

import { ArrowUpDown, Download, ListFilter, Search, Settings2, X } from "lucide-react";
import type { CatalogState, SortKey } from "@/types/catalog";
import type { CatalogStateUpdater } from "@/hooks/use-catalog-state";

function filterCount(state: CatalogState) {
  return state.categories.length
    + Number(state.priceMin !== undefined)
    + Number(state.priceMax !== undefined)
    + Number(state.note !== "all")
    + Number(state.official !== "all")
    + Number(state.image !== "all");
}

export function CatalogToolbar({
  state,
  setState,
  onOpenFilters,
  onOpenColumns,
  onOpenExport,
}: {
  state: CatalogState;
  setState: CatalogStateUpdater;
  onOpenFilters: () => void;
  onOpenColumns: () => void;
  onOpenExport: () => void;
}) {
  const activeFilters = filterCount(state);
  return (
    <div className="toolbar" role="search" aria-label="상품 검색과 목록 설정">
      <label className="search-field">
        <span className="sr-only">상품명, 규격, 분류 또는 비고 검색</span>
        <Search aria-hidden="true" />
        <input
          type="search"
          name="q"
          autoComplete="off"
          value={state.q}
          onChange={(event) => setState({ q: event.target.value, page: 1 })}
          placeholder="상품명, 규격, 분류 또는 비고 검색…"
        />
        {state.q && (
          <button type="button" onClick={() => setState({ q: "", page: 1 })} aria-label="검색어 지우기">
            <X aria-hidden="true" />
          </button>
        )}
      </label>

      <label className="sort-field">
        <ArrowUpDown aria-hidden="true" />
        <span className="sr-only">정렬 기준</span>
        <select
          name="sort"
          value={state.sort}
          onChange={(event) => setState({ sort: event.target.value as SortKey, page: 1 })}
          aria-label="정렬 기준"
        >
          <option value="source">원본 등록 순</option>
          <option value="name">상품명 순</option>
          <option value="category">분류 순</option>
          <option value="price-low">가격 낮은 순</option>
          <option value="price-high">가격 높은 순</option>
        </select>
      </label>

      <div className="toolbar-actions">
        <button type="button" className="toolbar-button" onClick={onOpenFilters} aria-haspopup="dialog">
          <ListFilter aria-hidden="true" />
          <span>필터{activeFilters ? ` ${activeFilters}` : ""}</span>
        </button>
        <button type="button" className="toolbar-button" onClick={onOpenColumns} aria-haspopup="dialog">
          <Settings2 aria-hidden="true" />
          <span>표시 열</span>
        </button>
        <button type="button" className="download-link" onClick={onOpenExport} aria-haspopup="dialog">
          <Download aria-hidden="true" />
          <span>데이터 받기</span>
        </button>
      </div>
    </div>
  );
}
