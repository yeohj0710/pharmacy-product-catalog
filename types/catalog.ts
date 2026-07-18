export type NoteFilter = "all" | "with" | "without";
export type OfficialFilter =
  | "all"
  | "confirmed"
  | "not_found"
  | "not_applicable"
  | "review_required"
  | "linked"
  | "unlinked";
export type ImageFilter = "all" | "with" | "without";

export type SortKey =
  | "source"
  | "name"
  | "category"
  | "price-low"
  | "price-high";

export type ColumnKey =
  | "name"
  | "capacity"
  | "category"
  | "price"
  | "etc"
  | "document_id"
  | "verification_status"
  | "manufacturer"
  | "image";

export type PageSize = 25 | 50 | 100;

export interface OfficialProductImage {
  url: string;
  kind: "package" | "pill" | "label" | "instruction";
  source_url: string;
  source_dataset_id: string;
  license: string;
  fetched_at: string;
  sha256?: string;
  mime_type?: string;
  local_path?: string;
}

export interface OfficialParagraphBlock {
  type: "paragraph";
  text: string;
}

export interface OfficialTableBlock {
  type: "table";
  headers: string[];
  rows: string[][];
}

export interface OfficialRichText {
  text: string;
  blocks: Array<OfficialParagraphBlock | OfficialTableBlock>;
}

export interface OfficialContent {
  schema_version: "1.0";
  normalization_version: string;
  efficacy?: OfficialRichText;
  dosage?: OfficialRichText;
  precautions?: OfficialRichText;
  professional_precautions?: OfficialRichText;
  patient_guidance?: OfficialRichText;
  medication_guide?: OfficialRichText;
  consumer_guidance?: Record<string, string>;
}

export interface Product {
  document_id: string;
  id: string;
  name: string;
  capacity: string;
  category: string;
  price: string;
  etc: string;
  updated: string;
  app_id: string;
  app_name: string;
  app_capacity: string;
  app_category: string;
  app_price: string;
  app_etc: string;
  app_updated: string;
  document_create_time: string;
  document_update_time: string;
  specification: string;
  displayed_price_krw: number;
  normalized_name: string;
  normalized_capacity: string;
  source_order: number;
  source_type: string;
  recorded_at: string;
  price_status: string;
  verification_status: string;
  image_url: string;
  image_source_url: string;
  image_rights_status: string;
  duplicate_group_id?: string;
  duplicate_group_size?: number;
  official_item_name?: string;
  official_manufacturer?: string;
  official_item_seq?: string;
  official_source_type?: string;
  official_source_url?: string;
  official_match_score?: number | string;
  official_match_status?: string;
  official_checked_at?: string;
  official_product_key?: string;
  official_domain?: string;
  official_barcode?: string;
  official_standard_codes?: string[];
  official_report_number?: string;
  official_udi_di?: string;
  official_category?: string;
  official_dosage_form?: string;
  official_route?: string;
  official_atc_code?: string;
  official_pack_unit?: string;
  official_storage?: string;
  official_valid_term?: string;
  official_appearance?: string;
  official_efficacy?: string;
  official_dosage?: string;
  official_precautions?: string;
  official_professional_precautions?: string;
  official_ingredients?: string[];
  official_active_ingredients?: string[];
  official_consumer_guidance?: Record<string, string>;
  official_images?: OfficialProductImage[];
  official_license?: string;
  official_upstream_updated_at?: string;
  official_raw_sha256?: string;
  official_content_status?: string;
  official_content?: OfficialContent;
  lookup_status?: string;
  match_alternatives?: unknown[];
  image_kind?: string;
  image_checked_at?: string;
  enrichment_status?: string;
  [key: `official_${string}`]: unknown;
}

export interface CatalogState {
  q: string;
  categories: string[];
  priceMin: number | undefined;
  priceMax: number | undefined;
  updatedFrom: string;
  updatedTo: string;
  note: NoteFilter;
  official: OfficialFilter;
  image: ImageFilter;
  sort: SortKey;
  cols: ColumnKey[];
  page: number;
  pageSize: PageSize;
  product: string;
}

export type CatalogFilters = Pick<
  CatalogState,
  | "q"
  | "categories"
  | "priceMin"
  | "priceMax"
  | "updatedFrom"
  | "updatedTo"
  | "note"
  | "official"
  | "image"
>;

export interface CatalogPage {
  items: Product[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  from: number;
  to: number;
}

export interface CatalogSummary {
  total: number;
  categoryCount: number;
  minPrice: number;
  maxPrice: number;
  medianPrice: number;
  withNote: number;
  officialLinked: number;
  withImage: number;
}

export const DEFAULT_FILTERS: CatalogFilters = {
  q: "",
  categories: [],
  priceMin: undefined,
  priceMax: undefined,
  updatedFrom: "",
  updatedTo: "",
  note: "all",
  official: "all",
  image: "all",
};

export const DEFAULT_COLUMNS: readonly ColumnKey[] = [
  "name",
  "capacity",
  "category",
  "price",
];
