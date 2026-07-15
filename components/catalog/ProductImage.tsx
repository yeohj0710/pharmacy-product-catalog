"use client";

/* eslint-disable @next/next/no-img-element */

import { ImageOff } from "lucide-react";
import { useState } from "react";
import type { Product } from "@/types/catalog";

export function approvedImageUrl(product: Product) {
  if (!product.image_url) return "";
  const rights = String(product.image_rights_status || "").toLowerCase();
  const allowed = ["approved", "verified", "official", "official_source_preview", "source_preview", "public_domain", "open_license", "재사용 가능", "공공누리", "공식 공개"];
  if (!allowed.some((status) => rights.includes(status))) return "";
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
      <div className={`image-placeholder ${large ? "large" : ""}`} aria-label="연결된 상품 이미지 없음">
        <ImageOff aria-hidden="true" />
        {large && <span>연결된 공식 상품 이미지가 없습니다.</span>}
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
