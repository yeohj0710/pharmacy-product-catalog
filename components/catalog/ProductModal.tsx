"use client";

import { ExternalLink, X } from "lucide-react";
import { useEffect, useRef } from "react";
import type { Product } from "@/types/catalog";
import { ProductImage } from "./ProductImage";

const money = new Intl.NumberFormat("ko-KR");

function safeHttps(value?: string) {
  if (!value) return "";
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function textValue(value: unknown) {
  if (Array.isArray(value)) return value.filter(Boolean).join(" · ");
  return typeof value === "string" ? value : "";
}

function structuredText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(structuredText).filter(Boolean).join(" · ");
  if (!value || typeof value !== "object") return "";
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => {
      const text = structuredText(item);
      return text ? `${key}: ${text}` : "";
    })
    .filter(Boolean)
    .join("\n");
}

function consumerGuidanceText(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const labels: Record<string, string> = {
    efficacy: "효능·효과",
    dosage: "복용 방법",
    warning: "복용 전 경고",
    precautions: "주의사항",
    interactions: "상호작용",
    side_effects: "부작용",
    storage: "보관 방법",
  };
  return Object.entries(value as Record<string, unknown>)
    .filter(([, text]) => typeof text === "string" && text)
    .map(([key, text]) => `${labels[key] || key}: ${text}`)
    .join("\n\n");
}

export function ProductModal({ product, onClose }: { product: Product; onClose: () => void }) {
  const modalRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";
    modalRef.current?.querySelector<HTMLElement>("button")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab" || !modalRef.current) return;
      const focusable = [...modalRef.current.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])")].filter((element) => !element.hasAttribute("disabled"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", keydown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", keydown);
      previousFocus?.focus();
    };
  }, [onClose]);

  const officialSourceUrl = safeHttps(typeof product.official_source_url === "string" ? product.official_source_url : "");
  const insertPdfUrl = safeHttps(typeof product.official_insert_pdf_url === "string" ? product.official_insert_pdf_url : "");
  const imageSourceUrl = safeHttps(product.image_source_url);
  const sourceUrl = officialSourceUrl || imageSourceUrl;
  const sourceLabel = officialSourceUrl.includes("health.kr") ? "약학정보원 원문 열기" : officialSourceUrl ? "제품 정보 원문 열기" : "이미지 출처 열기";
  const officialManufacturer = typeof product.official_manufacturer === "string" ? product.official_manufacturer : "";
  const officialPermitDate = structuredText(product.official_permit_date);
  const officialInsurance = structuredText(product.official_insurance);
  const basicDetails = [
    ["비고", product.etc],
    ["제조사", officialManufacturer],
    ["제형", product.official_dosage_form],
    ["포장단위", product.official_pack_unit],
    ["투여경로", product.official_route],
    ["허가일", officialPermitDate],
    ["보험정보", officialInsurance],
  ].filter(([, value]) => typeof value === "string" && value.trim());
  const officialSectionCandidates: Array<[string, string]> = [
    ["효능·효과", textValue(product.official_efficacy)],
    ["용법·용량", textValue(product.official_dosage)],
    ["사용상의 주의사항", textValue(product.official_precautions)],
    ["전문가 주의사항", textValue(product.official_professional_precautions)],
    ["유효성분", textValue(product.official_active_ingredients)],
    ["전체 성분", textValue(product.official_ingredients)],
    ["첨가제", structuredText(product.official_additives)],
    ["소비자 복약정보", consumerGuidanceText(product.official_consumer_guidance)],
    ["복약 안내", structuredText(product.official_patient_guidance)],
    ["의약품 설명", structuredText(product.official_medication_summary)],
    ["복약지도", structuredText(product.official_medication_guide)],
    ["저장방법", textValue(product.official_storage)],
    ["제품 성상", structuredText(product.official_appearance)],
    ["식별정보", structuredText(product.official_identification)],
    ["의약품 분류", structuredText(product.official_category)],
    ["ATC 분류", structuredText(product.official_atc_code)],
    ["KPIC 약효분류", structuredText(product.official_kpic_atc)],
    ["DUR 병용금기", structuredText(product.official_dur_contraindications)],
    ["DUR 연령금기", structuredText(product.official_dur_age)],
    ["DUR 임부금기", structuredText(product.official_dur_pregnancy)],
    ["DUR 고령자 주의", structuredText(product.official_dur_senior)],
    ["DUR 최대용량", structuredText(product.official_dur_max_dose)],
    ["DUR 최대투여기간", structuredText(product.official_dur_max_period)],
    ["DUR 분할주의", structuredText(product.official_dur_split_dosage)],
  ];
  const officialSections = officialSectionCandidates.filter(([, value]) => Boolean(value));
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={modalRef} className="modal modal-shell" role="dialog" aria-modal="true" aria-labelledby="product-title" aria-describedby="product-price-warning">
        <header className="modal-header">
          <div><span className="eyebrow">상품 상세</span><strong>{product.category || "미분류"}</strong></div>
          <button type="button" className="icon-button modal-close" onClick={onClose} aria-label="상품 상세 닫기"><X aria-hidden="true" /></button>
        </header>
        <div className="modal-body">
          <div className="modal-grid">
            <ProductImage product={product} large />
            <div>
              <h2 id="product-title">{product.name}</h2>
              <p className="modal-spec">{product.capacity || product.specification || "규격 미입력"}</p>
              <div className="modal-price"><span>가격</span><strong>{money.format(product.displayed_price_krw)}원</strong></div>
              <p className="price-warning" id="product-price-warning">실제 판매 가격이나 재고와 다를 수 있습니다. 가격과 취급 여부는 방문할 약국에 확인하세요.</p>
            </div>
          </div>
          {basicDetails.length > 0 && (
            <dl className="detail-list">
              {basicDetails.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
          )}
          {officialSections.length > 0 && (
            <section className="official-detail-section" aria-labelledby="official-detail-title">
              <div className="official-detail-heading">
                <h3 id="official-detail-title">약학정보원 제품 상세정보</h3>
              </div>
              <div className="official-detail-list">
                {officialSections.map(([label, value]) => (
                  <details key={label} open={label === "효능·효과" || label === "용법·용량"}>
                    <summary>{label}</summary>
                    <p>{value}</p>
                  </details>
                ))}
              </div>
              <p className="official-license">의약품을 사용하기 전에는 제품 설명서와 의료전문가의 안내를 확인하세요.</p>
            </section>
          )}
          {sourceUrl && <a className="source-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">{sourceLabel} <ExternalLink aria-hidden="true" /></a>}
          {insertPdfUrl && <a className="source-link" href={insertPdfUrl} target="_blank" rel="noopener noreferrer">제품 설명서 원문 열기 <ExternalLink aria-hidden="true" /></a>}
        </div>
      </section>
    </div>
  );
}
