import type {
  CatalogFilters,
  CatalogPage,
  CatalogSummary,
  Product,
  SortKey,
} from "../../types/catalog.ts";

const PRODUCT_STRING_FIELDS = [
  "document_id",
  "id",
  "name",
  "capacity",
  "category",
  "price",
  "etc",
  "updated",
  "app_id",
  "app_name",
  "app_capacity",
  "app_category",
  "app_price",
  "app_etc",
  "app_updated",
  "document_create_time",
  "document_update_time",
  "specification",
  "normalized_name",
  "normalized_capacity",
  "source_type",
  "recorded_at",
  "price_status",
  "verification_status",
  "image_url",
  "image_source_url",
  "image_rights_status",
] as const satisfies readonly (keyof Product)[];

const REQUIRED_NON_EMPTY_FIELDS = [
  "document_id",
  "id",
  "name",
  "capacity",
  "category",
  "price",
  "updated",
  "app_id",
  "app_name",
  "app_capacity",
  "app_category",
  "app_price",
  "app_updated",
  "specification",
  "normalized_name",
  "normalized_capacity",
  "source_type",
  "recorded_at",
  "price_status",
  "verification_status",
] as const satisfies readonly (keyof Product)[];

const PRODUCT_FIELDS = new Set<string>([
  ...PRODUCT_STRING_FIELDS,
  "displayed_price_krw",
  "source_order",
  "duplicate_group_id",
  "duplicate_group_size",
  "image_kind",
  "image_checked_at",
  "enrichment_status",
  "match_alternatives",
]);

const koreanCollator = new Intl.Collator("ko", {
  numeric: true,
  sensitivity: "base",
});

function assertRecord(value: unknown, index: number): asserts value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${index + 1}번째 상품이 객체가 아닙니다.`);
  }
}

function comparableDate(value: string): string {
  const digits = value.replace(/\D/g, "");
  return digits.length >= 8 ? digits.slice(0, 8) : "";
}

function isPresent(value: unknown): boolean {
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "boolean") return value;
  return value !== null && value !== undefined;
}

function hasOfficialInformation(product: Product): boolean {
  const status = product.official_match_status;
  if (typeof status === "string") {
    const normalized = status.trim().toLocaleLowerCase("ko-KR");
    if (["확정", "연결", "연결됨", "검증 완료", "confirmed", "linked", "verified"].includes(normalized)) {
      return true;
    }
    if ([
      "미연결",
      "검수 대기",
      "후보",
      "unlinked",
      "pending",
      "candidate",
      "not_found",
      "not_applicable",
      "review_required",
    ].includes(normalized)) {
      return false;
    }
  }

  return Object.entries(product).some(([key, value]) => {
    if (!key.startsWith("official_") || !isPresent(value)) return false;
    return !/(?:^|_)(?:match_)?(?:status|score|candidate|checked_at|matched_at)$/.test(key);
  });
}

function hasImage(product: Product): boolean {
  if (!product.image_url.trim()) return false;
  const rights = product.image_rights_status.toLocaleLowerCase("ko-KR");
  return ["approved", "verified", "official", "official_source_preview", "public_domain", "open_license", "재사용 가능", "공공누리", "공식 공개"]
    .some((status) => rights.includes(status));
}

function searchableText(product: Product): string {
  const officialValues = Object.entries(product)
    .filter(([key]) => key.startsWith("official_"))
    .map(([, value]) => (typeof value === "string" ? value : ""));
  return [
    product.name,
    product.capacity,
    product.category,
    product.etc,
    product.document_id,
    product.id,
    ...officialValues,
  ]
    .join(" ")
    .normalize("NFC")
    .toLocaleLowerCase("ko-KR");
}

export function validateProducts(input: unknown): Product[] {
  if (!Array.isArray(input)) {
    throw new TypeError("상품 데이터의 최상위 값은 배열이어야 합니다.");
  }

  const ids = new Set<string>();
  const documentIds = new Set<string>();

  return input.map((value, index) => {
    assertRecord(value, index);

    for (const key of Object.keys(value)) {
      if (!PRODUCT_FIELDS.has(key) && !key.startsWith("official_")) {
        throw new TypeError(`${index + 1}번째 상품에 허용되지 않은 필드 '${key}'가 있습니다.`);
      }
    }

    for (const field of PRODUCT_STRING_FIELDS) {
      if (typeof value[field] !== "string") {
        throw new TypeError(`${index + 1}번째 상품의 '${field}' 값은 문자열이어야 합니다.`);
      }
    }
    for (const field of REQUIRED_NON_EMPTY_FIELDS) {
      if (!(value[field] as string).trim()) {
        throw new TypeError(`${index + 1}번째 상품의 '${field}' 값이 비어 있습니다.`);
      }
    }

    if (
      typeof value.displayed_price_krw !== "number" ||
      !Number.isFinite(value.displayed_price_krw) ||
      value.displayed_price_krw <= 0
    ) {
      throw new TypeError(`${index + 1}번째 상품의 'displayed_price_krw' 값은 양수여야 합니다.`);
    }
    if (
      typeof value.source_order !== "number" ||
      !Number.isInteger(value.source_order) ||
      value.source_order <= 0
    ) {
      throw new TypeError(`${index + 1}번째 상품의 'source_order' 값은 양의 정수여야 합니다.`);
    }

    const id = value.id as string;
    const documentId = value.document_id as string;
    if (ids.has(id)) throw new TypeError(`중복 상품 ID가 있습니다: ${id}`);
    if (documentIds.has(documentId)) {
      throw new TypeError(`중복 Firestore 문서 ID가 있습니다: ${documentId}`);
    }
    ids.add(id);
    documentIds.add(documentId);

    return value as unknown as Product;
  });
}

export function filterProducts(
  products: readonly Product[],
  filters: CatalogFilters,
): Product[] {
  const query = filters.q.trim().normalize("NFC").toLocaleLowerCase("ko-KR");
  const selectedCategories = new Set(filters.categories);
  const from = comparableDate(filters.updatedFrom);
  const to = comparableDate(filters.updatedTo);

  return products.filter((product) => {
    if (query && !searchableText(product).includes(query)) return false;
    if (selectedCategories.size && !selectedCategories.has(product.category)) return false;
    if (filters.priceMin != null && product.displayed_price_krw < filters.priceMin) return false;
    if (filters.priceMax != null && product.displayed_price_krw > filters.priceMax) return false;

    const updated = comparableDate(product.updated);
    if (from && (!updated || updated < from)) return false;
    if (to && (!updated || updated > to)) return false;

    const withNote = product.etc.trim().length > 0;
    if (filters.note === "with" && !withNote) return false;
    if (filters.note === "without" && withNote) return false;

    const officialLinked = hasOfficialInformation(product);
    if (filters.official === "linked" && !officialLinked) return false;
    if (filters.official === "unlinked" && officialLinked) return false;
    if (
      ["confirmed", "not_found", "not_applicable", "review_required"].includes(filters.official) &&
      product.official_match_status !== filters.official
    ) return false;

    const imageAvailable = hasImage(product);
    if (filters.image === "with" && !imageAvailable) return false;
    if (filters.image === "without" && imageAvailable) return false;

    return true;
  });
}

export function sortProducts(products: readonly Product[], sort: SortKey): Product[] {
  return products
    .map((product, index) => ({ product, index }))
    .sort((left, right) => {
      const a = left.product;
      const b = right.product;
      let compared = 0;

      if (sort === "source") compared = a.source_order - b.source_order;
      if (sort === "name") compared = koreanCollator.compare(a.name, b.name);
      if (sort === "category") {
        compared = koreanCollator.compare(a.category, b.category);
        if (!compared) compared = koreanCollator.compare(a.name, b.name);
      }
      if (sort === "price-low") compared = a.displayed_price_krw - b.displayed_price_krw;
      if (sort === "price-high") compared = b.displayed_price_krw - a.displayed_price_krw;

      return compared || left.index - right.index;
    })
    .map(({ product }) => product);
}

export function paginateProducts(
  products: readonly Product[],
  requestedPage: number,
  requestedPageSize: number,
): CatalogPage {
  const pageSize = Number.isInteger(requestedPageSize) && requestedPageSize > 0
    ? requestedPageSize
    : 25;
  const total = products.length;
  const totalPages = total ? Math.ceil(total / pageSize) : 0;
  const page = totalPages
    ? Math.min(Math.max(Math.trunc(requestedPage) || 1, 1), totalPages)
    : 1;
  const start = (page - 1) * pageSize;
  const items = products.slice(start, start + pageSize);

  return {
    items,
    page,
    pageSize,
    total,
    totalPages,
    from: items.length ? start + 1 : 0,
    to: items.length ? start + items.length : 0,
  };
}

export function catalogSummary(products: readonly Product[]): CatalogSummary {
  const prices = products
    .map((product) => product.displayed_price_krw)
    .filter((price) => Number.isFinite(price) && price > 0)
    .sort((a, b) => a - b);
  const middle = Math.floor(prices.length / 2);
  const medianPrice = prices.length === 0
    ? 0
    : prices.length % 2
      ? prices[middle]
      : (prices[middle - 1] + prices[middle]) / 2;

  return {
    total: products.length,
    categoryCount: new Set(products.map((product) => product.category)).size,
    minPrice: prices[0] ?? 0,
    maxPrice: prices.at(-1) ?? 0,
    medianPrice,
    withNote: products.filter((product) => product.etc.trim()).length,
    officialLinked: products.filter(hasOfficialInformation).length,
    withImage: products.filter(hasImage).length,
  };
}
