import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";

const sources = [
  { label: "식품의약품안전처 의약품개요정보(e약은요)", href: "https://www.data.go.kr/data/15075057/openapi.do" },
  { label: "식품의약품안전처 의약품 제품 허가정보", href: "https://www.data.go.kr/data/15095677/openapi.do" },
  { label: "국가법령정보센터 저작권법 제93조", href: "https://law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0093&lsiSeq=283335&urlMode=lsScJoRltInfoR" },
  { label: "국가법령정보센터 저작권법 제94조", href: "https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0094&lsiSeq=283335&urlMode=lsScJoRltInfoR" },
  { label: "국가법령정보센터 부정경쟁방지법 제2조", href: "https://www.law.go.kr/lsLawLinkInfo.do?chrClsCd=010202&lsJoLnkSeq=900358570" },
  { label: "국가법령정보센터 표시·광고법 제3조", href: "https://www.law.go.kr/LSW/lsLawLinkInfo.do?chrClsCd=010202&lsJoLnkSeq=900554254" },
];

export default function DataPolicyPage() {
  return (
    <main className="policy-page">
      <Link href="/" className="back-link"><ArrowLeft aria-hidden="true" /> 상품 목록으로 돌아가기</Link>
      <header className="policy-hero">
        <span className="eyebrow">DATA POLICY</span>
        <h1>데이터 보존·공개 기준</h1>
        <p>가격을 포함한 원자료는 로컬에 보존합니다. 외부 공개는 데이터베이스 권리, 이미지 이용 조건과 가격 오인 위험을 별도로 확인한 뒤 결정합니다.</p>
      </header>

      <section className="policy-block">
        <h2>로컬 아카이브에 보존하는 정보</h2>
        <ul>
          <li>Firestore 원본의 상품명, 규격, 분류, 가격, 비고와 갱신일</li>
          <li>원본 문서 ID, 생성 시각, 수정 시각과 조회 날짜</li>
          <li>화면 녹화 OCR 대조본의 출처 파일, 화면 위치, 문자 인식 신뢰도와 검수 상태</li>
          <li>식약처 공개 데이터에서 별도로 확인한 제품명, 업체명, 품목기준코드와 낱알이미지</li>
        </ul>
        <p>로컬에 보존한 모든 정보가 외부 공개 대상이라는 뜻은 아닙니다.</p>
      </section>
      <section className="policy-block">
        <h2>외부에 제공하지 않는 정보</h2>
        <ul>
          <li>현재 판매가, 현재 재고 또는 구매 가능 여부</li>
          <li>의약품 구매·예약·배송 기능</li>
          <li>원본 앱 화면, 광고, 로고 또는 앱이 촬영한 재고 사진</li>
          <li>녹화 중 표시된 메신저 알림, 사람 이름과 계정 정보</li>
          <li>재사용 근거를 확인하지 못한 제3자 이미지</li>
        </ul>
      </section>
      <section className="policy-block">
        <h2>가격을 읽는 방법</h2>
        <p>표시 가격은 2026년 7월 15일 Firestore 조회 당시 앱 데이터값입니다. 현재 판매가·재고가 아닙니다. 실제 가격과 취급 여부는 방문할 약국에 확인하세요. OCR 값은 정본이 아니라 대조 자료로만 사용합니다.</p>
      </section>
      <section className="policy-block">
        <h2>외부 공개 전 반드시 확인할 항목</h2>
        <ul>
          <li>앱 이용약관, 접근 권한과 수집 과정에 기술적 보호조치 우회가 없었는지 확인합니다.</li>
          <li>전체 또는 상당한 부분의 공개와 반복적 추출이 데이터베이스제작자의 권리와 충돌하는지 검토합니다.</li>
          <li>비영리 연구 목적 예외와 데이터베이스의 일반적인 이용에 저촉되지 않는다는 요건을 검토합니다.</li>
          <li>이미지마다 재사용 근거, 원본 URL, 제공기관과 확인일을 기록합니다.</li>
          <li>실제 운영 연락처와 정정·삭제 접수 절차를 마련합니다.</li>
        </ul>
      </section>
      <section className="policy-block">
        <h2>출처와 독립성</h2>
        <p>이 사이트는 메가팩토리약국 및 ‘창고형약국 약값체크’ 앱의 운영자와 제휴·승인 관계가 없습니다. 브랜드명은 출처와 사실관계를 설명하는 데 필요한 범위에서만 사용합니다. 저작권법에는 비영리 교육·학술·연구 목적의 데이터베이스 권리 제한 규정이 있지만 조건이 있으므로, ‘연구용’ 표지만으로 공개가 허용된다고 보지 않습니다.</p>
      </section>
      <section className="policy-block">
        <h2>정정·삭제 요청</h2>
        <p>상품명, 분류, 가격 또는 출처가 잘못되었거나 권리 침해가 우려되면 운영자에게 상품명과 수정 근거를 보내 주세요. 외부 공개 전 실제 운영 연락처를 설정합니다. 요청받은 항목은 확인이 끝날 때까지 외부 공개 대상에서 제외합니다.</p>
      </section>
      <section className="policy-block">
        <h2>참고한 공식 자료</h2>
        <div className="source-list">{sources.map((source) => <a key={source.href} href={source.href} target="_blank" rel="noreferrer">{source.label}<ExternalLink aria-hidden="true" /></a>)}</div>
      </section>
      <p className="legal-note">이 문서는 법률 자문이 아닙니다. 전체 데이터의 외부 공개, 공개 API 제공 또는 상업적 이용 전에는 대한민국 변호사의 검토가 필요합니다.</p>
    </main>
  );
}
