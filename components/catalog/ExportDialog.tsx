"use client";

import { Download, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Product } from "@/types/catalog";
import { EXPORT_FIELDS, createCsv, createExportFilename, createJson, downloadBlob } from "@/lib/catalog/download";
import type { ExportFieldKey } from "@/lib/catalog/download";

type Scope = "all" | "filtered" | "selected";
type Format = "csv" | "json";

export function ExportDialog({ open, allProducts, filteredProducts, selectedProducts, initialScope = "filtered", onClose }: {
  open: boolean;
  allProducts: Product[];
  filteredProducts: Product[];
  selectedProducts: Product[];
  initialScope?: Scope;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const [scope, setScope] = useState<Scope>(initialScope);
  const [format, setFormat] = useState<Format>("csv");
  const [fields, setFields] = useState<ExportFieldKey[]>(EXPORT_FIELDS.map((field) => field.key));
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.focus({ preventScroll: true });
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>("button, input, select, [tabindex]:not([tabindex='-1'])")].filter((element) => !element.hasAttribute("disabled"));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (!document.activeElement || document.activeElement === dialogRef.current || !dialogRef.current.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", keydown);
    return () => { document.body.style.overflow = previousOverflow; window.removeEventListener("keydown", keydown); previousFocus?.focus(); };
  }, [onClose, open]);
  if (!open) return null;

  const rows = scope === "all" ? allProducts : scope === "selected" ? selectedProducts : filteredProducts;
  const toggle = (key: ExportFieldKey) => setFields((current) => current.includes(key) ? current.filter((field) => field !== key) : [...current, key]);
  const download = () => {
    if (!rows.length || !fields.length) return;
    const blob = format === "csv" ? createCsv(rows, fields) : createJson(rows, fields);
    const scopeLabel = scope === "all" ? "전체" : scope === "selected" ? `선택_${rows.length}개` : `필터_${rows.length}개`;
    downloadBlob(blob, createExportFilename(scopeLabel, format));
    setMessage(`${rows.length.toLocaleString("ko-KR")}개 상품의 ${format.toUpperCase()} 파일을 만들었습니다.`);
  };

  return (
    <div className="modal-backdrop export-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="modal modal-shell export-dialog" role="dialog" aria-modal="true" aria-labelledby="export-title" tabIndex={-1}>
        <header className="modal-header"><div><span className="eyebrow">원본 필드 보존</span><h2 id="export-title">데이터 받기</h2></div><button type="button" className="icon-button modal-close" onClick={onClose} aria-label="데이터 받기 닫기"><X aria-hidden="true" /></button></header>
        <div className="modal-body">
          <fieldset className="export-scope"><legend>다운로드 범위</legend>
            <label><input type="radio" name="scope" value="all" checked={scope === "all"} onChange={() => setScope("all")} /><span>전체 상품 <small>{allProducts.length.toLocaleString("ko-KR")}개</small></span></label>
            <label><input type="radio" name="scope" value="filtered" checked={scope === "filtered"} onChange={() => setScope("filtered")} /><span>현재 검색 결과 <small>{filteredProducts.length.toLocaleString("ko-KR")}개</small></span></label>
            <label><input type="radio" name="scope" value="selected" checked={scope === "selected"} disabled={!selectedProducts.length} onChange={() => setScope("selected")} /><span>선택한 상품 <small>{selectedProducts.length.toLocaleString("ko-KR")}개</small></span></label>
          </fieldset>

          <fieldset className="export-format"><legend>파일 형식</legend><label><input type="radio" name="format" value="csv" checked={format === "csv"} onChange={() => setFormat("csv")} />CSV</label><label><input type="radio" name="format" value="json" checked={format === "json"} onChange={() => setFormat("json")} />JSON</label></fieldset>

          <fieldset className="export-fields"><legend>포함할 필드 <small>{fields.length}/{EXPORT_FIELDS.length}</small></legend>
            <div className="field-actions"><button type="button" onClick={() => setFields(EXPORT_FIELDS.map((field) => field.key))}>전체 선택</button><button type="button" onClick={() => setFields([])}>전체 해제</button></div>
            <div className="checkbox-grid">{EXPORT_FIELDS.map((field) => <label key={field.key}><input type="checkbox" checked={fields.includes(field.key)} onChange={() => toggle(field.key)} /><span>{field.label}</span></label>)}</div>
          </fieldset>

          <p className="export-help">표시 열과 별개로 다운로드 필드를 선택합니다. CSV는 스프레드시트 수식 실행을 막도록 안전하게 처리합니다.</p>
          <div className="panel-actions"><button type="button" className="secondary-button" onClick={onClose}>취소</button><button type="button" className="primary-button" disabled={!rows.length || !fields.length} onClick={download}><Download aria-hidden="true" />{rows.length.toLocaleString("ko-KR")}개 {format.toUpperCase()} 받기</button></div>
          <p className="sr-only" aria-live="polite">{message}</p>
        </div>
      </section>
    </div>
  );
}
