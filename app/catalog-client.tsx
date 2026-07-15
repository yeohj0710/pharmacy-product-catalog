"use client";

import { AlertCircle, ChevronRight, Database, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActiveFilterChips } from "@/components/catalog/ActiveFilterChips";
import { CatalogPagination } from "@/components/catalog/CatalogPagination";
import { CatalogToolbar } from "@/components/catalog/CatalogToolbar";
import { ColumnPicker } from "@/components/catalog/ColumnPicker";
import { ExportDialog } from "@/components/catalog/ExportDialog";
import { FilterPanel } from "@/components/catalog/FilterPanel";
import { ProductCardList } from "@/components/catalog/ProductCardList";
import { ProductModal } from "@/components/catalog/ProductModal";
import { ProductTable } from "@/components/catalog/ProductTable";
import { SelectionBar } from "@/components/catalog/SelectionBar";
import { useCatalogState } from "@/hooks/use-catalog-state";
import { catalogSummary, filterProducts, paginateProducts, sortProducts, validateProducts } from "@/lib/catalog/catalog";
import type { Product } from "@/types/catalog";

const DATA_URL = "/data/enrichment-queue.json";
const money = new Intl.NumberFormat("ko-KR");

export default function CatalogClient() {
  const { state, setState, resetFilters } = useCatalogState();
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportScope, setExportScope] = useState<"all" | "filtered" | "selected">("filtered");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    const controller = new AbortController();
    fetch(DATA_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("상품 데이터 파일을 읽지 못했습니다.");
        return response.json();
      })
      .then((data: unknown) => setProducts(validateProducts(data)))
      .catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const product of products) counts.set(product.category || "미분류", (counts.get(product.category || "미분류") || 0) + 1);
    return [...counts].sort((left, right) => right[1] - left[1]);
  }, [products]);
  const summary = useMemo(() => catalogSummary(products), [products]);
  const filtered = useMemo(() => sortProducts(filterProducts(products, state), state.sort), [products, state]);
  const page = useMemo(() => paginateProducts(filtered, state.page, state.pageSize), [filtered, state.page, state.pageSize]);
  const selectedProducts = useMemo(() => products.filter((product) => selectedIds.has(product.id)), [products, selectedIds]);
  const selectedProduct = useMemo(() => products.find((product) => product.id === state.product || product.document_id === state.product) || null, [products, state.product]);

  useEffect(() => {
    if (!loading && page.page !== state.page) setState({ page: page.page });
  }, [loading, page.page, setState, state.page]);

  const toggleSelected = useCallback((id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);
  const togglePage = useCallback((checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const product of page.items) {
        if (checked) next.add(product.id);
        else next.delete(product.id);
      }
      return next;
    });
  }, [page.items]);
  const openProduct = useCallback((product: Product) => setState({ product: product.id }), [setState]);
  const closeProduct = useCallback(() => setState({ product: "" }), [setState]);
  const closeExport = useCallback(() => setExportOpen(false), []);
  const openExport = (scope: "all" | "filtered" | "selected") => { setExportScope(scope); setExportOpen(true); };
  const dialogOpen = Boolean(selectedProduct) || exportOpen;

  return (
    <>
      <main id="main-content" inert={dialogOpen ? true : undefined} aria-hidden={dialogOpen ? true : undefined}>
        <header className="site-header">
          <Link href="/" className="brand"><Database aria-hidden="true" /><span>약국 상품 아카이브</span></Link>
          <nav aria-label="주요 메뉴"><a href="#catalog">상품 목록</a><Link href="/data-policy">데이터 기준</Link></nav>
        </header>

        <section className="hero">
          <div className="hero-copy"><span className="eyebrow">PHARMACY PRODUCT ARCHIVE</span><h1>약국 상품 정보를<br />한곳에서 찾습니다</h1><p>앱 데이터에서 확인한 상품명, 규격, 분류와 가격을 검색할 수 있게 정리한 독립적인 연구용 목록입니다.</p></div>
          <div className="hero-notice"><ShieldCheck aria-hidden="true" /><div><strong>가격 안내</strong><p>앱에 표시된 가격 정보이며 실제 판매 가격이나 재고와 다를 수 있습니다.</p></div></div>
        </section>

        <section className="summary" aria-label="데이터 요약">
          <div><span>원본 문서</span><strong>776</strong><small>개</small></div>
          <div><span>확인된 상품</span><strong>{loading ? "—" : summary.total.toLocaleString("ko-KR")}</strong><small>개</small></div>
          <div><span>확인된 분류</span><strong>{loading ? "—" : summary.categoryCount}</strong><small>개</small></div>
          <div><span>표시 가격 중앙값</span><strong>{loading ? "—" : money.format(summary.medianPrice)}</strong><small>원</small></div>
        </section>

        <section className="catalog-section" id="catalog">
          <div className="section-heading"><div><span className="eyebrow">전체 상품</span><h2>상품 목록</h2></div><p>검색 조건을 조합하고 필요한 상품과 필드를 골라 내려받을 수 있습니다.</p></div>
          <CatalogToolbar state={state} setState={setState} onOpenFilters={() => { setFilterOpen((open) => !open); setColumnsOpen(false); }} onOpenColumns={() => { setColumnsOpen((open) => !open); setFilterOpen(false); }} onOpenExport={() => openExport("filtered")} />
          {filterOpen && <FilterPanel open state={state} setState={setState} categories={categories} onClose={() => setFilterOpen(false)} />}
          {columnsOpen && <ColumnPicker open state={state} setState={setState} onClose={() => setColumnsOpen(false)} />}
          <ActiveFilterChips state={state} setState={setState} onReset={resetFilters} />

          <div className="result-bar" aria-live="polite"><strong>{filtered.length.toLocaleString("ko-KR")}개 상품</strong><span>표시 가격은 실제 판매 가격과 다를 수 있습니다.</span></div>
          {loading && <div className="state-panel" role="status"><Database className="spin-soft" aria-hidden="true" /><strong>상품 데이터를 불러오고 있습니다…</strong></div>}
          {error && <div className="state-panel error" role="alert"><AlertCircle aria-hidden="true" /><strong>상품 데이터를 불러오지 못했습니다.</strong><p>{error} 페이지를 새로고침해 다시 시도하세요.</p></div>}
          {!loading && !error && filtered.length === 0 && <div className="state-panel"><Search aria-hidden="true" /><strong>검색 조건에 맞는 상품이 없습니다.</strong><p>검색어나 필터를 줄여 다시 확인하세요.</p></div>}
          {!loading && !error && filtered.length > 0 && (
            <>
              <ProductTable products={page.items} columns={state.cols} selectedIds={selectedIds} onToggle={toggleSelected} onTogglePage={togglePage} onOpen={openProduct} />
              <ProductCardList products={page.items} columns={state.cols} selectedIds={selectedIds} onToggle={toggleSelected} onOpen={openProduct} />
              <CatalogPagination page={page.page} pageSize={page.pageSize} total={page.total} onPageChange={(next) => { setState({ page: next }); document.getElementById("catalog")?.scrollIntoView({ block: "start" }); }} onPageSizeChange={(pageSize) => setState({ pageSize: pageSize as 25 | 50 | 100, page: 1 })} />
            </>
          )}
        </section>

        <section className="principles">
          <div><span className="eyebrow">데이터 원칙</span><h2>사실 정보와 출처를<br />분리해 기록합니다</h2></div>
          <div className="principle-list">
            <article><span>01</span><div><strong>상품 정보를 그대로 보존합니다</strong><p>상품명, 규격, 분류와 가격을 원본대로 저장합니다.</p></div></article>
            <article><span>02</span><div><strong>공식 정보는 별도로 연결합니다</strong><p>식약처 공개 데이터와 제조사 공식 페이지에서 확인한 정보만 공식 정보로 표시합니다.</p></div></article>
            <article><span>03</span><div><strong>원본 화면과 로고를 복제하지 않습니다</strong><p>앱 화면, 광고, 로고와 제3자 이미지는 공개 데이터에 포함하지 않습니다.</p></div></article>
          </div>
          <Link className="policy-link" href="/data-policy">데이터 수집·공개 기준 보기 <ChevronRight aria-hidden="true" /></Link>
        </section>
        <footer><p>메가팩토리약국 또는 ‘창고형약국 약값체크’ 앱과 제휴·승인 관계가 없는 독립적인 연구용 아카이브입니다.</p><Link href="/data-policy">데이터 기준 및 정정 안내</Link></footer>
        <SelectionBar selectedCount={selectedIds.size} filteredCount={filtered.length} onSelectFiltered={() => setSelectedIds(new Set(filtered.map((product) => product.id)))} onExport={() => openExport("selected")} onClear={() => setSelectedIds(new Set())} />
      </main>
      {selectedProduct && <ProductModal product={selectedProduct} onClose={closeProduct} />}
      {exportOpen && <ExportDialog open allProducts={products} filteredProducts={filtered} selectedProducts={selectedProducts} initialScope={exportScope} onClose={closeExport} />}
    </>
  );
}
