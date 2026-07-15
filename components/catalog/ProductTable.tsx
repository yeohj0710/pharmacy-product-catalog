"use client";

import { CheckCircle2 } from "lucide-react";
import { useEffect, useRef } from "react";
import type { ColumnKey, Product } from "@/types/catalog";
import { approvedImageUrl, ProductImage } from "./ProductImage";

const money = new Intl.NumberFormat("ko-KR");

export function ProductTable({
  products,
  columns,
  selectedIds,
  onToggle,
  onTogglePage,
  onOpen,
}: {
  products: Product[];
  columns: ColumnKey[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  onTogglePage: (selected: boolean) => void;
  onOpen: (product: Product) => void;
}) {
  const pageSelected = products.filter((product) => selectedIds.has(product.id)).length;
  const allSelected = products.length > 0 && pageSelected === products.length;
  const selectPageRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (selectPageRef.current) selectPageRef.current.indeterminate = pageSelected > 0 && !allSelected;
  }, [allSelected, pageSelected]);
  const show = (key: string) => columns.includes(key as ColumnKey);

  return (
    <div className="product-table desktop-results">
      <table>
        <caption className="sr-only">약국 상품 목록</caption>
        <thead>
          <tr>
            <th scope="col" className="select-column"><input ref={selectPageRef} type="checkbox" checked={allSelected} onChange={(event) => onTogglePage(event.target.checked)} aria-label="현재 페이지 상품 전체 선택" /></th>
            <th scope="col">상품</th>
            {show("capacity") && <th scope="col">규격</th>}
            {show("category") && <th scope="col">분류</th>}
            {show("price") && <th scope="col" className="numeric-column">가격</th>}
            {show("etc") && <th scope="col">원본 비고</th>}
            {show("document_id") && <th scope="col">원본 문서 ID</th>}
            {show("verification_status") && <th scope="col">확인 상태</th>}
            {show("manufacturer") && <th scope="col">공식 등록 업체</th>}
            {show("image") && <th scope="col">공식 이미지</th>}
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <tr key={product.id} className={selectedIds.has(product.id) ? "selected" : ""}>
              <td className="select-column"><input type="checkbox" checked={selectedIds.has(product.id)} onChange={() => onToggle(product.id)} aria-label={`${product.name} 선택`} /></td>
              <th scope="row">
                <button type="button" className="product-name-button" onClick={() => onOpen(product)}>
                  <ProductImage product={product} />
                  <span><strong>{product.name}</strong><small>상세 보기</small></span>
                </button>
              </th>
              {show("capacity") && <td>{product.capacity || product.specification || "미입력"}</td>}
              {show("category") && <td>{product.category || "미분류"}</td>}
              {show("price") && <td className="numeric-column"><strong>{money.format(product.displayed_price_krw)}원</strong></td>}
              {show("etc") && <td className="truncate-cell" title={product.etc || "없음"}>{product.etc || "없음"}</td>}
              {show("document_id") && <td className="document-id">{product.document_id || product.id}</td>}
              {show("verification_status") && <td><span className="status-cell"><CheckCircle2 aria-hidden="true" />원본 확인</span></td>}
              {show("manufacturer") && <td>{typeof product.official_manufacturer === "string" ? product.official_manufacturer : "미연결"}</td>}
              {show("image") && <td>{approvedImageUrl(product) ? "표시 가능" : "미연결·미검수"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
