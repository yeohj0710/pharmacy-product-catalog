import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "약국 상품 아카이브",
    template: "%s | 약국 상품 아카이브",
  },
  description: "상품명과 공개 제품 정보를 확인하는 독립적인 연구용 데이터 사이트",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
