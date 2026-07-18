"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";
import { compactOfficialText, dedupeLabeledText, formatConsumerGuidance } from "@/lib/catalog/text";
import type { OfficialRichText, Product } from "@/types/catalog";
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

function safeSourceUrl(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "";
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "";
  } catch {
    return "";
  }
}

function OfficialContentValue({ fallback, rich }: { fallback: string; rich?: OfficialRichText }) {
  if (!rich?.blocks?.length) return <p>{fallback}</p>;
  return (
    <div className="official-rich-text">
      {rich.blocks.map((block, index) => {
        if (block.type === "paragraph") return <p key={`paragraph-${index}`}>{block.text}</p>;
        return (
          <div className="official-table-scroll" key={`table-${index}`}>
            <table>
              {block.headers.length > 0 && (
                <thead><tr>{block.headers.map((cell, cellIndex) => <th key={cellIndex} scope="col">{cell}</th>)}</tr></thead>
              )}
              <tbody>
                {block.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>{row.map((cell, cellIndex) => (
                    block.headers.length === 0 && cellIndex === 0 && cell
                      ? <th key={cellIndex} scope="row">{cell}</th>
                      : <td key={cellIndex}>{cell}</td>
                  ))}</tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

export function ProductModal({ product, onClose }: { product: Product; onClose: () => void }) {
  const modalRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";
    modalRef.current?.focus({ preventScroll: true });
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab" || !modalRef.current) return;
      const focusable = [...modalRef.current.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])")].filter((element) => !element.hasAttribute("disabled"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!document.activeElement || document.activeElement === modalRef.current || !modalRef.current.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }
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
  const officialSourceUrl = safeSourceUrl(product.official_source_url);
  const imageSourceUrl = safeSourceUrl(product.image_source_url);
  const sourceLinks = [
    officialSourceUrl && ["약학정보원 제품 원문", officialSourceUrl],
    imageSourceUrl && imageSourceUrl !== officialSourceUrl && ["제품 이미지 출처", imageSourceUrl],
  ].filter(Boolean) as Array<[string, string]>;
  const officialPermitDate = structuredText(product.official_permit_date);
  const officialInsurance = structuredText(product.official_insurance);
  const richByLabel = new Map<string, OfficialRichText | undefined>([
    ["효능·효과", product.official_content?.efficacy],
    ["용법·용량", product.official_content?.dosage],
    ["사용상의 주의사항", product.official_content?.precautions],
    ["전문가 주의사항", product.official_content?.professional_precautions],
    ["복약 안내", product.official_content?.patient_guidance],
    ["복약지도", product.official_content?.medication_guide],
  ]);
  const basicDetails = [
    ["비고", product.etc],
    ["제조사", officialManufacturer],
    ["제형", product.official_dosage_form],
    ["포장단위", product.official_pack_unit],
    ["투여경로", product.official_route],
    ["허가일", officialPermitDate],
    ["보험정보", officialInsurance],
  ].filter(([, value]) => typeof value === "string" && value.trim().length > 0);
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
        ["소비자 복약정보", formatConsumerGuidance(product.official_consumer_guidance)],
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
      items: dedupeLabeledText(group.items as Array<[string, string]>),
    }))
    .filter((group) => group.items.length > 0);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={modalRef} className="modal modal-shell" role="dialog" aria-modal="true" aria-labelledby="product-title" aria-describedby="product-price-warning" tabIndex={-1}>
        <header className="modal-header">
          <div><span className="eyebrow">상품 상세</span><strong>{product.category || "미분류"}</strong></div>
          <button type="button" className="icon-button modal-close" onClick={onClose} aria-label="상품 상세 닫기"><X aria-hidden="true" /></button>
        </header>
        <div className="modal-body">
          <div className="modal-grid">
            <ProductImage product={product} large />
            <div className="modal-product-copy">
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
          {sourceLinks.length > 0 && (
            <nav className="product-source-links" aria-label="상품 출처">
              {sourceLinks.map(([label, url]) => (
                <a href={url} key={label} target="_blank" rel="noopener noreferrer">{label}</a>
              ))}
            </nav>
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
                          <OfficialContentValue fallback={value} rich={richByLabel.get(label)} />
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
