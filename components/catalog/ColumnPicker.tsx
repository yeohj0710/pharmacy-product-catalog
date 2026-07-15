"use client";

import { RotateCcw, X } from "lucide-react";
import { DEFAULT_COLUMNS } from "@/types/catalog";
import type { CatalogState, ColumnKey } from "@/types/catalog";
import type { CatalogStateUpdater } from "@/hooks/use-catalog-state";

export const COLUMN_OPTIONS = [
  { key: "name" as ColumnKey, label: "상품", required: true },
  { key: "capacity" as ColumnKey, label: "규격" },
  { key: "category" as ColumnKey, label: "분류" },
  { key: "price" as ColumnKey, label: "가격" },
  { key: "etc" as ColumnKey, label: "비고" },
  { key: "manufacturer" as ColumnKey, label: "제조사" },
  { key: "image" as ColumnKey, label: "상품 이미지" },
];

export function ColumnPicker({ open, state, setState, onClose }: { open: boolean; state: CatalogState; setState: CatalogStateUpdater; onClose: () => void }) {
  if (!open) return null;
  const toggle = (key: ColumnKey) => {
    if (key === ("name" as ColumnKey)) return;
    setState({ cols: state.cols.includes(key) ? state.cols.filter((column) => column !== key) : [...state.cols, key] });
  };
  return (
    <section className="column-picker" role="dialog" aria-modal="false" aria-labelledby="column-picker-title">
      <header className="panel-header">
        <div><span className="eyebrow">목록 설정</span><h3 id="column-picker-title">표시할 열</h3></div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="표시 열 설정 닫기"><X aria-hidden="true" /></button>
      </header>
      <p className="panel-help">표시 열 설정은 다운로드 필드에 영향을 주지 않습니다.</p>
      <div className="column-options">
        {COLUMN_OPTIONS.map((column) => (
          <label key={column.key}>
            <input type="checkbox" checked={state.cols.includes(column.key)} disabled={column.required} onChange={() => toggle(column.key)} />
            <span>{column.label}{column.required && <small>필수</small>}</span>
          </label>
        ))}
      </div>
      <footer className="panel-actions">
        <button type="button" className="secondary-button" onClick={() => setState({ cols: [...DEFAULT_COLUMNS] })}><RotateCcw aria-hidden="true" />기본값 복원</button>
        <button type="button" className="primary-button" onClick={onClose}>적용 완료</button>
      </footer>
    </section>
  );
}
