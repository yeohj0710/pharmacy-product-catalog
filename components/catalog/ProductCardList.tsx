"use client";

import type { ColumnKey, Product } from "@/types/catalog";
import { approvedImageUrl, ProductImage } from "./ProductImage";

const money = new Intl.NumberFormat("ko-KR");

export function ProductCardList({ products, columns, selectedIds, onToggle, onOpen }: {
  products: Product[];
  columns: ColumnKey[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  onOpen: (product: Product) => void;
}) {
  const show = (key: string) => columns.includes(key as ColumnKey);
  return (
    <ul className="product-card-list mobile-results" aria-label="약국 상품 목록">
      {products.map((product) => (
        <li key={product.id} className={selectedIds.has(product.id) ? "selected" : ""}>
          <article>
            <label className="card-select"><input type="checkbox" checked={selectedIds.has(product.id)} onChange={() => onToggle(product.id)} /><span className="sr-only">{product.name} 선택</span></label>
            <ProductImage product={product} />
            <div className="card-copy">
              <h3>{product.name}</h3>
              <p>{product.capacity || product.specification || "규격 미입력"}</p>
              {show("price") && <strong className="card-price">{money.format(product.displayed_price_krw)}원</strong>}
            </div>
            <button type="button" className="card-detail" onClick={() => onOpen(product)} aria-label={`${product.name} 상세 보기`}>상세 보기</button>
            <dl>
              {show("category") && <div><dt>분류</dt><dd>{product.category || "미분류"}</dd></div>}
              {show("etc") && <div><dt>비고</dt><dd>{product.etc || "없음"}</dd></div>}
              {show("manufacturer") && <div><dt>제조사</dt><dd>{typeof product.official_manufacturer === "string" ? product.official_manufacturer : "정보 없음"}</dd></div>}
              {show("image") && <div><dt>상품 이미지</dt><dd>{approvedImageUrl(product) ? "있음" : "없음"}</dd></div>}
            </dl>
          </article>
        </li>
      ))}
    </ul>
  );
}
