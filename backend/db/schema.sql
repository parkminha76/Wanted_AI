-- InfoGuard DB 스키마 v3 (TiDB Cloud / MySQL 호환)
--
-- v2 -> v3 변경 요약 (db/CHANGELOG_v3.md 참고):
--   - findings.reason, scan_results.error: 자유 텍스트 -> 고정 코드(ENUM).
--     실제 코드 목록/변환 로직은 db/codes.py 참고.
--   - findings.evidence: 화이트리스트 검증(db/codes.py:sanitize_evidence)을
--     반드시 거친 뒤에만 저장. 스키마 자체(JSON 컬럼)는 동일하지만 애플리케이션
--     레벨에서 강제한다.
--   - hidden_commands.scan_result_id 제거. finding_id만 남기고, scan_result는
--     findings 테이블을 통해 조인해서 구한다 (서로 다른 검사 결과를 가리키는
--     불일치 자체가 발생할 수 없게 함).
--   - users.session_id 주석 정정: "익명화"가 아니라 "직접 식별자 제거".
--     로그인 인증 토큰이 아니라 비인증 세션 토큰이라는 점 명시.
--   - 부모-자식 관계에 ON DELETE CASCADE 추가 (삭제 순서를 사람이 신경 쓸 필요 없게).
--   - 필수 상태/카운트 컬럼에 NOT NULL 추가.
--   - "집계 결과만 저장" -> 정확히는 "원문 없이 집계 및 탐지 메타데이터 저장".

-- ---------------------------------------------------------------------------
-- 1. companies
-- ---------------------------------------------------------------------------
CREATE TABLE companies (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    plan ENUM('free', 'enterprise') NOT NULL DEFAULT 'free',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- 2. users
--
-- session_id: "익명 방문자 세션 식별자"다. 로그인 인증 수단은 아니지만, 이
-- 값 하나만 알면 해당 세션의 스캔 이력/훈련 진행상황에 접근할 수 있으므로
-- 사실상 접근 자격(access credential) 역할을 한다. "비인증 토큰"이라는
-- 표현은 이 사실을 가릴 수 있어 쓰지 않는다.
--
-- company_admin 권한: session_id만으로 company_admin 역할을 신뢰해서는
-- 안 된다. 관리자 기능(조직 통계 조회 등)은 별도의 인증·인가(비밀번호,
-- OAuth 등)를 API 레벨에서 반드시 거쳐야 한다 — DB 스키마가 보장해줄 수
-- 없는 부분이라 애플리케이션 책임으로 명시해둔다.
--
-- department는 조직 통계 기능이 실제로 필요할 때만 채운다 (기본 NULL 권장).
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    company_id BIGINT NULL,
    role ENUM('individual', 'employee', 'company_admin') NOT NULL DEFAULT 'individual',
    session_id CHAR(36) NOT NULL UNIQUE,
    department VARCHAR(100) NULL,           -- 조직 통계 기능 쓸 때만 채울 것 (기본 NULL 권장)
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

-- ---------------------------------------------------------------------------
-- 3. scan_results — 원문 없이 "집계 및 탐지 메타데이터" 저장
--    (findings에 개별 탐지 메타데이터가 있으므로 "집계만"은 부정확한 표현이었음)
-- ---------------------------------------------------------------------------
CREATE TABLE scan_results (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    file_extension VARCHAR(10) NOT NULL DEFAULT '',
    risk_score FLOAT NOT NULL DEFAULT 0.0,
    error_code ENUM('parse_failed', 'unsupported_format', 'file_too_large', 'timeout', 'unknown') NULL,
    status ENUM('완료', '취소', '실패') NOT NULL DEFAULT '완료',
    finding_counts JSON NOT NULL,   -- MySQL/TiDB는 JSON 컬럼에 리터럴 DEFAULT를
                                     -- 지정할 수 없다(버전에 따라 표현식 DEFAULT
                                     -- 지원이 다름). NOT NULL이므로 애플리케이션이
                                     -- INSERT 시 항상 값을 명시해야 한다 — 빈 경우
                                     -- '{}'를 직접 넣을 것. db/converters.py는
                                     -- 이미 항상 dict(빈 dict 포함)를 전달한다.
    filtered_count INT NOT NULL DEFAULT 0,
    has_hidden_command BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_scan_results_user_created (user_id, created_at)
);

-- ---------------------------------------------------------------------------
-- 4. findings — 개별 탐지 메타데이터. 원문/오프셋 없음.
--    reason은 고정 코드(ENUM)로만. evidence는 db/codes.py:sanitize_evidence()를
--    반드시 거친 값만 들어와야 한다 (스키마 레벨에서 강제 불가, 애플리케이션 책임).
-- ---------------------------------------------------------------------------
CREATE TABLE findings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    scan_result_id BIGINT NOT NULL,
    finding_ref VARCHAR(10) NULL,
    type VARCHAR(30) NOT NULL,
    confidence FLOAT NOT NULL,
    source ENUM('rule', 'ner', 'classifier', 'format', 'cnn') NOT NULL,
    reason_code ENUM(
        'format_match', 'checksum_pass', 'checksum_fail', 'ner_match',
        'classifier_high_confidence', 'classifier_low_confidence',
        'hidden_text_detected', 'injection_pattern_match', 'cnn_detection'
    ) NOT NULL,
    page INT NULL,
    evidence JSON NOT NULL,   -- sanitize_evidence() 통과분만. JSON 컬럼은 리터럴
                               -- DEFAULT를 못 걸므로(위 finding_counts와 동일 이유)
                               -- 애플리케이션이 항상 명시적으로 '{}' 또는 값을 전달.
    excluded BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (scan_result_id) REFERENCES scan_results(id) ON DELETE CASCADE,
    INDEX idx_findings_scan_excluded (scan_result_id, excluded)
);

-- ---------------------------------------------------------------------------
-- 5. hidden_commands — scan_result_id 제거. finding_id만으로 충분하고,
--    scan_result가 필요하면 findings.scan_result_id로 조인해서 구한다.
--    이렇게 하면 "서로 다른 검사 결과를 가리키는" 불일치가 구조적으로 불가능.
-- ---------------------------------------------------------------------------
CREATE TABLE hidden_commands (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    finding_id BIGINT NOT NULL UNIQUE,
    status ENUM('확인필요', '제거함', '무시함') NOT NULL DEFAULT '확인필요',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (finding_id) REFERENCES findings(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- 6. training_progress
-- ---------------------------------------------------------------------------
CREATE TABLE training_progress (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    level INT NOT NULL,
    status ENUM('진행중', '완료', '중단') NOT NULL DEFAULT '진행중',
    score INT NOT NULL DEFAULT 0,
    completed_at DATETIME NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- 7. training_events
-- ---------------------------------------------------------------------------
CREATE TABLE training_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    training_progress_id BIGINT NOT NULL,
    turn_no INT NOT NULL,
    detected_field VARCHAR(30) NULL,
    action ENUM('경고표시', '전송강행', '취소') NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (training_progress_id) REFERENCES training_progress(id) ON DELETE CASCADE,
    UNIQUE KEY uq_training_events_turn (training_progress_id, turn_no)
);

-- ---------------------------------------------------------------------------
-- 8. scam_cases — 본선 스코프, 변경 없음
-- ---------------------------------------------------------------------------
CREATE TABLE scam_cases (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    level INT NOT NULL,
    category VARCHAR(50) NULL,
    text TEXT NOT NULL,
    embedding_json JSON NULL,
    source VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);