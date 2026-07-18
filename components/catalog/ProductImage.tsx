"use client";

/* eslint-disable @next/next/no-img-element */

import { useState } from "react";
import type { Product } from "@/types/catalog";

export function approvedImageUrl(product: Product) {
  if (!product.image_url) return "";
  const rights = String(product.image_rights_status || "").toLowerCase();
  const allowed = new Set(["approved", "verified", "official", "official_source_preview", "public_domain", "open_license", "재사용 가능", "공공누리", "공식 공개"]);
  if (!allowed.has(rights)) return "";
  try {
    const url = new URL(product.image_url);
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

export function ProductImage({ product, large = false }: { product: Product; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  const imageUrl = approvedImageUrl(product);
  if (!imageUrl || failed) {
    return (
      <div className={`image-placeholder product-image-fallback ${large ? "large" : ""}`} aria-label={`${product.name} 대체 이미지`}>
        <strong aria-hidden="true">{product.name.slice(0, large ? 18 : 2)}</strong>
        {large && <span>{product.capacity || product.specification}</span>}
      </div>
    );
  }
  return (
    <div className={`product-image ${large ? "large" : ""}`}>
      <img
        src={imageUrl}
        alt={`${product.name} 상품 이미지`}
        width={large ? 230 : 66}
        height={large ? 230 : 66}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    </div>
  );
}
