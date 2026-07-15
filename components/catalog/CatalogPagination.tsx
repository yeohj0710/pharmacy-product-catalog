"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

function pageWindow(page: number, totalPages: number) {
  const start = Math.max(1, Math.min(page - 2, totalPages - 4));
  return Array.from({ length: Math.min(5, totalPages) }, (_, index) => start + index);
}

export function CatalogPagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(page, totalPages);
  const first = total ? (current - 1) * pageSize + 1 : 0;
  const last = Math.min(current * pageSize, total);
  return (
    <div className="catalog-pagination">
      <p><strong>{first.toLocaleString("ko-KR")}–{last.toLocaleString("ko-KR")}</strong> / {total.toLocaleString("ko-KR")}개</p>
      <nav aria-label="상품 목록 페이지">
        <button type="button" onClick={() => onPageChange(current - 1)} disabled={current <= 1} aria-label="이전 페이지"><ChevronLeft aria-hidden="true" /></button>
        {pageWindow(current, totalPages).map((number) => (
          <button type="button" key={number} onClick={() => onPageChange(number)} aria-current={number === current ? "page" : undefined} aria-label={`${number}페이지`}>{number}</button>
        ))}
        <button type="button" onClick={() => onPageChange(current + 1)} disabled={current >= totalPages} aria-label="다음 페이지"><ChevronRight aria-hidden="true" /></button>
      </nav>
      <label className="page-size"><span>페이지당</span><select value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))} aria-label="페이지당 상품 수"><option value="25">25개</option><option value="50">50개</option><option value="100">100개</option></select></label>
    </div>
  );
}
