"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";
import { compactOfficialText } from "@/lib/catalog/text";
import type { Product } from "@/types/catalog";
import { ProductImage } from "./ProductImage";

const money = new Intl.NumberFormat("ko-KR");

function textValue(value: unknown) {
  if (Array.isArray(value)) return compactOfficialText(value.filter(Boolean).join(" · "));
  return typeof value === "string" ? compactOfficialText(value) : "";
}

function structuredText(value: unknown): string {
  if (typeof value === "string") return compactOfficialText(value);
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
  return compactOfficialText(Object.entries(value as Record<string, unknown>)
    .filter(([, text]) => typeof text === "string" && text.trim().length > 0)
    .map(([key, text]) => `${labels[key] || key}: ${text}`)
    .join("\n"));
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
  const officialGroups = [
    {
      title: "효능과 복용",
      description: "사용 목적과 복용 방법, 주의사항",
      items: [
        ["효능·효과", textValue(product.official_efficacy)],
        ["용법·용량", textValue(product.official_dosage)],
        ["사용상의 주의사항", textValue(product.official_precautions)],
        ["전문가 주의사항", textValue(product.official_professional_precautions)],
      ],
    },
    {
      title: "성분",
      description: "유효성분과 첨가제",
      items: [
        ["유효성분", textValue(product.official_active_ingredients)],
        ["전체 성분", textValue(product.official_ingredients)],
        ["첨가제", structuredText(product.official_additives)],
      ],
    },
    {
      title: "복약 정보",
      description: "복용할 때 확인할 안내",
      items: [
        ["소비자 복약정보", consumerGuidanceText(product.official_consumer_guidance)],
        ["복약 안내", structuredText(product.official_patient_guidance)],
        ["의약품 설명", structuredText(product.official_medication_summary)],
        ["복약지도", structuredText(product.official_medication_guide)],
      ],
    },
    {
      title: "제품 정보",
      description: "보관, 외형과 의약품 분류",
      items: [
        ["저장방법", textValue(product.official_storage)],
        ["제품 성상", structuredText(product.official_appearance)],
        ["식별정보", structuredText(product.official_identification)],
        ["의약품 분류", structuredText(product.official_category)],
        ["ATC 분류", structuredText(product.official_atc_code)],
        ["KPIC 약효분류", structuredText(product.official_kpic_atc)],
      ],
    },
    {
      title: "복용 금기·주의 정보",
      description: "의약품 안전사용서비스(DUR) 기준",
      items: [
        ["DUR 병용금기", structuredText(product.official_dur_contraindications)],
        ["DUR 연령금기", structuredText(product.official_dur_age)],
        ["DUR 임부금기", structuredText(product.official_dur_pregnancy)],
        ["DUR 고령자 주의", structuredText(product.official_dur_senior)],
        ["DUR 최대용량", structuredText(product.official_dur_max_dose)],
        ["DUR 최대투여기간", structuredText(product.official_dur_max_period)],
        ["DUR 분할주의", structuredText(product.official_dur_split_dosage)],
      ],
    },
  ]
    .map((group) => ({
      ...group,
      items: group.items.filter(([, value]) => value.trim().length > 0) as Array<[string, string]>,
    }))
    .filter((group) => group.items.length > 0);
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
          {officialGroups.length > 0 && (
            <section className="official-detail-section" aria-labelledby="official-detail-title">
              <div className="official-detail-heading">
                <span className="eyebrow">공식 의약품 정보</span>
                <h3 id="official-detail-title">약학정보원 제품 정보</h3>
                <p>효능, 복용법, 성분과 주의사항을 항목별로 정리했습니다.</p>
              </div>
              <div className="official-detail-groups">
                {officialGroups.map((group, groupIndex) => (
                  <section className="official-detail-group" key={group.title} aria-labelledby={`official-group-${groupIndex}`}>
                    <header>
                      <h4 id={`official-group-${groupIndex}`}>{group.title}</h4>
                      <p>{group.description}</p>
                    </header>
                    <div className="official-detail-items">
                      {group.items.map(([label, value]) => (
                        <article className="official-detail-item" key={label}>
                          <h5>{label}</h5>
                          <p>{value}</p>
                        </article>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
              <p className="official-license">의약품을 사용하기 전에는 제품 설명서와 의료전문가의 안내를 확인하세요.</p>
            </section>
          )}
        </div>
      </section>
    </div>
  );
}
