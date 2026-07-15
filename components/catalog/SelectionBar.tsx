"use client";

import { Download, X } from "lucide-react";

export function SelectionBar({ selectedCount, filteredCount, onSelectFiltered, onExport, onClear }: {
  selectedCount: number;
  filteredCount: number;
  onSelectFiltered: () => void;
  onExport: () => void;
  onClear: () => void;
}) {
  if (!selectedCount) return null;
  return (
    <aside className="selection-bar" aria-live="polite" aria-label="선택한 상품 작업">
      <div><strong>{selectedCount.toLocaleString("ko-KR")}개 선택됨</strong><span>선택 항목은 현재 탭에서만 유지됩니다.</span></div>
      <div className="selection-actions">
        {selectedCount < filteredCount && <button type="button" className="secondary-button" onClick={onSelectFiltered}>검색 결과 {filteredCount.toLocaleString("ko-KR")}개 전체 선택</button>}
        <button type="button" className="primary-button" onClick={onExport}><Download aria-hidden="true" />선택 데이터 받기</button>
        <button type="button" className="icon-button" onClick={onClear} aria-label="선택 전체 해제"><X aria-hidden="true" /></button>
      </div>
    </aside>
  );
}
