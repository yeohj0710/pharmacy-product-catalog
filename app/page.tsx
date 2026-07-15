import type { Metadata } from "next";
import CatalogClient from "./catalog-client";

export const metadata: Metadata = {
  description: "약국 상품명, 규격, 분류와 가격을 검색하는 연구용 아카이브입니다.",
};

export default function Home() {
  return <CatalogClient />;
}
