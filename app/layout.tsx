import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "약국 상품 아카이브",
    template: "%s | 약국 상품 아카이브",
  },
  description: "약국 상품 776개를 검색·필터·정렬하고 필요한 데이터만 내려받는 독립적인 연구용 아카이브",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>
        <a className="skip-link" href="#main-content">본문으로 바로가기</a>
        {children}
      </body>
    </html>
  );
}
