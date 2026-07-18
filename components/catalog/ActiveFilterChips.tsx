"use client";

import { X } from "lucide-react";
import type { CatalogState } from "@/types/catalog";
import type { CatalogStateUpdater } from "@/hooks/use-catalog-state";

export function ActiveFilterChips({ state, setState, onReset }: { state: CatalogState; setState: CatalogStateUpdater; onReset: () => void }) {
  const chips: Array<{ key: string; label: string; remove: () => void }> = [];
  const officialLabels: Record<string, string> = {
    confirmed: "수록 확인",
    not_found: "검색 결과 없음",
    not_applicable: "수록 대상 아님",
    review_required: "확인 필요",
    linked: "연결됨",
    unlinked: "미연결",
  };
  for (const category of state.categories) {
    chips.push({ key: `category-${category}`, label: `분류: ${category}`, remove: () => setState({ categories: state.categories.filter((item) => item !== category), page: 1 }) });
  }
  if (state.priceMin !== undefined) chips.push({ key: "priceMin", label: `${state.priceMin.toLocaleString("ko-KR")}원 이상`, remove: () => setState({ priceMin: undefined, page: 1 }) });
  if (state.priceMax !== undefined) chips.push({ key: "priceMax", label: `${state.priceMax.toLocaleString("ko-KR")}원 이하`, remove: () => setState({ priceMax: undefined, page: 1 }) });
  if (state.note !== "all") chips.push({ key: "note", label: `비고 ${state.note === "with" ? "있음" : "없음"}`, remove: () => setState({ note: "all", page: 1 }) });
  if (state.official !== "all") chips.push({ key: "official", label: `약학정보원: ${officialLabels[state.official]}`, remove: () => setState({ official: "all", page: 1 }) });
  if (state.image !== "all") chips.push({ key: "image", label: `상품 이미지 ${state.image === "with" ? "있음" : "없음"}`, remove: () => setState({ image: "all", page: 1 }) });
  if (!chips.length) return null;
  return (
    <div className="active-filters" aria-label="적용된 필터">
      {chips.map((chip) => (
        <button type="button" key={chip.key} onClick={chip.remove} aria-label={`${chip.label} 필터 삭제`}>
          <span>{chip.label}</span><X aria-hidden="true" />
        </button>
      ))}
      <button type="button" className="reset-filters" onClick={onReset}>필터 전체 초기화</button>
    </div>
  );
}
