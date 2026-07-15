"use client";

/* eslint-disable @next/next/no-img-element */
import {
  AlertCircle,
  ArrowUpDown,
  CheckCircle2,
  ChevronRight,
  Database,
  Download,
  ExternalLink,
  ImageOff,
  Info,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

type Product = {
  id: string;
  document_id?: string;
  document_create_time?: string;
  document_update_time?: string;
  updated?: string;
  name: string;
  price?: string;
  capacity?: string;
  etc?: string;
  normalized_name?: string;
  specification?: string;
  category?: string;
  displayed_price_krw: number;
  price_status?: string;
  source_video?: string;
  source_second?: number;
  source_frame?: number;
  recorded_at?: string;
  source_type?: string;
  ocr_confidence?: number;
  observations?: number;
  verification_status?: string;
  image_url?: string;
  image_source_url?: string;
  image_rights_status?: string;
  official_item_name?: string;
  official_manufacturer?: string;
  official_item_seq?: string;
};

type SortKey = "source" | "name" | "price-low" | "price-high";

const DATA_URL = "/data/products.json";
const PAGE_SIZE = 60;

function formatPrice(value: number) {
  return new Intl.NumberFormat("ko-KR").format(value) + "원";
}

function formatAppDate(value?: string) {
  if (!value || !/^\d{8}$/.test(value)) return value || "날짜 미확인";
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}

function ProductImage({ product, large = false }: { product: Product; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  if (!product.image_url || failed) {
    return (
      <div className={`image-placeholder ${large ? "large" : ""}`} aria-label="공식 이미지 없음">
        <ImageOff aria-hidden="true" />
        {large && <span>아직 연결된 공식 이미지가 없습니다.</span>}
      </div>
    );
  }
  return (
    <div className={`product-image ${large ? "large" : ""}`}>
      <img src={product.image_url} alt={`${product.name} 공식 제품 이미지`} onError={() => setFailed(true)} />
    </div>
  );
}

function ProductModal({ product, onClose }: { product: Product; onClose: () => void }) {
  const modalRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const previous = document.body.style.overflow;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";
    modalRef.current?.querySelector<HTMLElement>("button, a, input, select, textarea, [tabindex]:not([tabindex='-1'])")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab" || !modalRef.current) return;
      const focusable = [...modalRef.current.querySelectorAll<HTMLElement>("button, a, input, select, textarea, [tabindex]:not([tabindex='-1'])")]
        .filter((element) => !element.hasAttribute("disabled"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, [onClose]);

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section ref={modalRef} className="modal" role="dialog" aria-modal="true" aria-labelledby="product-title">
        <button className="icon-button modal-close" onClick={onClose} aria-label="상품 상세 닫기">
          <X aria-hidden="true" />
        </button>
        <div className="modal-grid">
          <ProductImage product={product} large />
          <div>
            <span className="eyebrow">{product.category || "미분류"}</span>
            <h2 id="product-title">{product.name}</h2>
            {product.specification && <p className="modal-spec">{product.specification}</p>}
            <div className="modal-price">
              <span>2026년 7월 15일 조회 당시 앱 가격</span>
              <strong>{formatPrice(product.displayed_price_krw)}</strong>
            </div>
            <p className="price-warning">
              현재 판매가나 재고를 뜻하지 않습니다. 실제 가격과 취급 여부는 방문할 약국에 확인하세요.
            </p>
          </div>
        </div>

        <dl className="detail-list">
          <div><dt>원본 문서 ID</dt><dd>{product.document_id || product.id}</dd></div>
          <div><dt>앱 데이터 갱신일</dt><dd>{formatAppDate(product.updated)}</dd></div>
          <div><dt>규격</dt><dd>{product.capacity || product.specification || "미입력"}</dd></div>
          <div><dt>원본 비고</dt><dd>{product.etc || "없음"}</dd></div>
          <div><dt>조회 날짜</dt><dd>{product.recorded_at || "2026-07-15"}</dd></div>
          <div><dt>확인 상태</dt><dd>{product.verification_status || "Firestore 원본 확인"}</dd></div>
          {product.official_manufacturer && <div><dt>공식 등록 업체</dt><dd>{product.official_manufacturer}</dd></div>}
        </dl>

        {product.image_source_url ? (
          <a className="source-link" href={product.image_source_url} target="_blank" rel="noreferrer">
            공식 제품 정보 열기 <ExternalLink aria-hidden="true" />
          </a>
        ) : (
          <div className="source-pending"><Info aria-hidden="true" /> 공식 제품 정보와 연결하기 전입니다.</div>
        )}
      </section>
    </div>
  );
}

export default function CatalogClient() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("전체");
  const [sort, setSort] = useState<SortKey>("source");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [selected, setSelected] = useState<Product | null>(null);
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());

  useEffect(() => {
    fetch(DATA_URL)
      .then((response) => {
        if (!response.ok) throw new Error("상품 데이터 파일을 읽지 못했습니다.");
        return response.json();
      })
      .then((data: Product[]) => setProducts(data))
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, []);

  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of products) {
      const key = item.category || "미분류";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts].sort((a, b) => b[1] - a[1]);
  }, [products]);

  const filtered = useMemo(() => {
    const list = products.filter((item) => {
      const haystack = `${item.name} ${item.specification || ""} ${item.category || ""}`.toLowerCase();
      return (category === "전체" || item.category === category) && (!deferredQuery || haystack.includes(deferredQuery));
    });
    return list.sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name, "ko");
      if (sort === "price-low") return a.displayed_price_krw - b.displayed_price_krw;
      if (sort === "price-high") return b.displayed_price_krw - a.displayed_price_krw;
      return (a.document_id || a.id).localeCompare(b.document_id || b.id, "ko");
    });
  }, [products, category, deferredQuery, sort]);

  const stats = useMemo(() => {
    const prices = products.map((item) => item.displayed_price_krw).filter(Boolean).sort((a, b) => a - b);
    const median = prices.length ? prices[Math.floor(prices.length / 2)] : 0;
    const official = products.filter((item) => item.official_item_seq).length;
    return { median, official };
  }, [products]);

  return (
    <>
    <main inert={selected ? true : undefined} aria-hidden={selected ? true : undefined}>
      <header className="site-header">
        <Link href="/" className="brand"><Database aria-hidden="true" /><span>약국 상품 아카이브</span></Link>
        <nav aria-label="주요 메뉴">
          <a href="#catalog">상품 목록</a>
          <Link href="/data-policy">데이터 기준</Link>
        </nav>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">PHARMACY PRODUCT ARCHIVE</span>
          <h1>약국 상품 정보를<br />한곳에서 찾습니다</h1>
          <p>조회한 앱 데이터에서 상품명, 규격, 분류와 표시 가격을 검색할 수 있게 정리한 독립적인 연구용 목록입니다.</p>
        </div>
        <div className="hero-notice">
          <ShieldCheck aria-hidden="true" />
          <div><strong>가격 기준을 먼저 확인하세요</strong><p>가격은 2026년 7월 15일 조회 당시 비공식 앱 데이터값입니다. 현재 판매가나 재고가 아닙니다.</p></div>
        </div>
      </section>

      <section className="summary" aria-label="데이터 요약">
        <div><span>원본 문서</span><strong>776</strong><small>개</small></div>
        <div><span>확인된 상품</span><strong>{loading ? "—" : products.length.toLocaleString("ko-KR")}</strong><small>개</small></div>
        <div><span>확인된 분류</span><strong>{loading ? "—" : categories.length}</strong><small>개</small></div>
        <div><span>표시 가격 중앙값</span><strong>{loading ? "—" : stats.median.toLocaleString("ko-KR")}</strong><small>원</small></div>
      </section>

      <section className="catalog-section" id="catalog">
        <div className="section-heading">
          <div><span className="eyebrow">전체 상품</span><h2>상품 목록</h2></div>
          <p>상품을 누르면 원본 문서 정보와 앱 데이터 갱신일을 확인할 수 있습니다.</p>
        </div>

        <div className="toolbar">
          <label className="search-field">
            <span className="sr-only">상품명, 규격 또는 분류 검색</span>
            <Search aria-hidden="true" />
            <input value={query} onChange={(event) => { setQuery(event.target.value); setVisibleCount(PAGE_SIZE); }} placeholder="상품명, 규격 또는 분류 검색" />
            {query && <button onClick={() => { setQuery(""); setVisibleCount(PAGE_SIZE); }} aria-label="검색어 지우기"><X aria-hidden="true" /></button>}
          </label>
          <label className="sort-field">
            <ArrowUpDown aria-hidden="true" />
            <span className="sr-only">정렬 기준</span>
            <select value={sort} onChange={(event) => { setSort(event.target.value as SortKey); setVisibleCount(PAGE_SIZE); }}>
              <option value="source">원본 등록 순</option>
              <option value="name">상품명 순</option>
              <option value="price-low">가격 낮은 순</option>
              <option value="price-high">가격 높은 순</option>
            </select>
          </label>
          <a className="download-link" href="/data/catalog.csv" download><Download aria-hidden="true" /> CSV 받기</a>
        </div>

        <div className="category-scroll" aria-label="상품 분류">
          <button className={category === "전체" ? "active" : ""} onClick={() => { setCategory("전체"); setVisibleCount(PAGE_SIZE); }}>전체 <span>{products.length}</span></button>
          {categories.map(([name, count]) => (
            <button key={name} className={category === name ? "active" : ""} onClick={() => { setCategory(name); setVisibleCount(PAGE_SIZE); }}>{name} <span>{count}</span></button>
          ))}
        </div>

        <div className="result-bar" aria-live="polite"><strong>{filtered.length.toLocaleString("ko-KR")}개 상품</strong><span>표시 가격은 현재 가격이 아닙니다.</span></div>

        {loading && <div className="state-panel" role="status"><Database className="spin-soft" aria-hidden="true" /><strong>상품 데이터를 불러오고 있습니다.</strong></div>}
        {error && <div className="state-panel error" role="alert"><AlertCircle aria-hidden="true" /><strong>{error}</strong><p>데이터 추출 작업을 마친 뒤 다시 새로고침하세요.</p></div>}
        {!loading && !error && filtered.length === 0 && <div className="state-panel"><Search aria-hidden="true" /><strong>검색 조건에 맞는 상품이 없습니다.</strong><p>검색어를 줄이거나 다른 분류를 선택하세요.</p></div>}

        {!loading && !error && filtered.length > 0 && (
          <div className="product-table" aria-label="약국 상품 목록">
            <div className="table-head" aria-hidden="true">
              <span>상품</span><span>분류</span><span>조회 당시 앱 가격</span><span>확인</span><span />
            </div>
            {filtered.slice(0, visibleCount).map((product) => (
              <button className="product-row" key={product.id} onClick={() => setSelected(product)} aria-label={`${product.name} 상세 보기`}>
                <span className="product-main"><ProductImage product={product} /><span><strong>{product.name}</strong><small>{product.specification || "규격 미확인"}</small></span></span>
                <span className="category-cell">{product.category || "미분류"}</span>
                <span className="price-cell"><strong>{formatPrice(product.displayed_price_krw)}</strong><small>2026-07-15 조회값</small></span>
                <span className="status-cell">
                  <><CheckCircle2 aria-hidden="true" /> 원본 확인</>
                </span>
                <ChevronRight className="row-arrow" aria-hidden="true" />
              </button>
            ))}
          </div>
        )}

        {visibleCount < filtered.length && <button className="load-more" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>상품 더 보기 <span>{Math.min(PAGE_SIZE, filtered.length - visibleCount)}개</span></button>}
      </section>

      <section className="principles">
        <div><span className="eyebrow">데이터 원칙</span><h2>사실 정보와 출처를<br />분리해 기록합니다</h2></div>
        <div className="principle-list">
          <article><span>01</span><div><strong>앱 데이터값은 조회 날짜를 붙입니다</strong><p>상품명과 가격을 확인한 날짜와 원본 문서 ID를 함께 저장합니다.</p></div></article>
          <article><span>02</span><div><strong>공식 정보는 별도로 연결합니다</strong><p>식약처 공개 데이터와 제조사 공식 페이지에서 확인한 정보만 공식 정보로 표시합니다.</p></div></article>
          <article><span>03</span><div><strong>원본 화면과 로고를 복제하지 않습니다</strong><p>앱 화면, 광고, 로고와 제3자 이미지는 공개 데이터에 포함하지 않습니다.</p></div></article>
        </div>
        <Link className="policy-link" href="/data-policy">데이터 수집·공개 기준 보기 <ChevronRight aria-hidden="true" /></Link>
      </section>

      <footer>
        <p>메가팩토리약국 또는 ‘창고형약국 약값체크’ 앱과 제휴·승인 관계가 없는 독립적인 연구용 아카이브입니다.</p>
        <Link href="/data-policy">데이터 기준 및 정정 안내</Link>
      </footer>
    </main>
    {selected && <ProductModal product={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
