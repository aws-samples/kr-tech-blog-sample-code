-- Smart Agentic AI Redshift 완전 설정 스크립트
-- Redshift 에디터에서 바로 실행 가능
-- =====================================================
-- 1. 테이블 생성
-- =====================================================

CREATE TABLE Domain (
    DomainID varchar(30),
    DomainNM varchar(100),
    Description varchar(500),
    load_timestamp TIMESTAMP DEFAULT GETDATE()
);

CREATE TABLE Agent (
    DomainID varchar(30),
    AgentID varchar(30),
    AgentNM varchar(100),
    Score DECIMAL(10,2),
    Description varchar(500),
    load_timestamp TIMESTAMP DEFAULT GETDATE()
   );

CREATE TABLE Tool (
    DomainID VARCHAR(30),
    AgentID VARCHAR(30), 
    ToolID VARCHAR(30),
    ToolNM VARCHAR(100),
    ToolSpec TEXT,
    Description VARCHAR(500),
    load_timestamp TIMESTAMP DEFAULT GETDATE()
)
DISTKEY(DomainID)
SORTKEY(AgentID)
;

--drop table UserInfo;
CREATE TABLE UserInfo(
    UserID VARCHAR(30),
    UserNM VARCHAR(100),
    UserProfile VARCHAR(500),
    LastLoginDT VARCHAR(14),
    CreationDT VARCHAR(14),
    load_timestamp TIMESTAMP DEFAULT GETDATE()
)
DISTKEY (UserID)
SORTKEY (LastLoginDT);

CREATE TABLE UserSession(
    UserID VARCHAR(30),
    SessionID VARCHAR(30),
    SessionNM VARCHAR(100),
    SessionSummary VARCHAR(1000),
    SessionStartDT VARCHAR(14),
    DtlFileLoc VARCHAR(100),
    load_timestamp TIMESTAMP DEFAULT GETDATE()
)
DISTKEY (UserID)
SORTKEY (SessionID);

CREATE TABLE UserSessionProcess(
    UserID VARCHAR(30),
    SessionID VARCHAR(30),
    ProcessID VARCHAR(30),
    UserPrompt VARCHAR(1000),
    ProcNM VARCHAR(100),
    ProcDesc VARCHAR(500),
    ProcDT VARCHAR(14),
    load_timestamp TIMESTAMP DEFAULT GETDATE()
)
DISTKEY (UserID)
SORTKEY (SessionID, ProcessID);

--drop table user_tool_mapping_hist;
CREATE TABLE user_tool_mapping_hist (
    UserID VARCHAR(30),
    SessionID VARCHAR(30),
    ProcessID VARCHAR(30),
    AgentID VARCHAR(30),
    ToolID VARCHAR(30),
    ToolNM VARCHAR(100),
    ToolValues TEXT,
    TransactDT VARCHAR(20),
    SuccYN VARCHAR(1),
    ResultMsg TEXT,
    load_timestamp TIMESTAMP DEFAULT GETDATE()
)
DISTKEY (UserID)
SORTKEY (SessionID, ProcessID, AgentID, ToolID);


-- 분석용 스테이징 테이블
CREATE TABLE IF NOT EXISTS agent_tool_analysis_staging (
    UserID VARCHAR(30),
    SessionID VARCHAR(30),
    ProcessID VARCHAR(30),
    DomainID VARCHAR(30),
    AgentID VARCHAR(30),
    ToolID VARCHAR(30),
    ToolNM VARCHAR(100),
    execution_date DATE,
    execution_datetime TIMESTAMP,
    success_flag BOOLEAN,
    tool_values TEXT,
    result_message VARCHAR(500)
)
DISTKEY (UserID)
SORTKEY (execution_date);

-- 에이전트 스코어 계산용 집계 테이블
--drop table agent_score_summary;
CREATE TABLE IF NOT EXISTS agent_score_summary (
    DomainID VARCHAR(30),
    AgentID VARCHAR(30),
    AgentNM VARCHAR(100),
    total_executions INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    success_rate DECIMAL(5,4),
    last_execution_date DATE,
    days_since_last_exec INTEGER,
    time_decay_factor DECIMAL(10,8),
    calculated_score DECIMAL(10,2),
    updated_at TIMESTAMP DEFAULT GETDATE()
)
DISTKEY (DomainID)
SORTKEY (calculated_score);

-- 사용자별 프로세스 패턴 분석 테이블
CREATE TABLE IF NOT EXISTS user_process_patterns (
    UserID VARCHAR(30),
    process_pattern VARCHAR(200),
    agent_sequence VARCHAR(200),
    tool_sequence VARCHAR(500),
    execution_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    avg_execution_time DECIMAL(8,2),
    pattern_score DECIMAL(10,2),
    first_used_date DATE,
    last_used_date DATE,
    is_recommended BOOLEAN DEFAULT FALSE
)
DISTKEY (UserID)
SORTKEY (pattern_score);


-- =====================================================
-- 2. 원본 데이터 입력
-- =====================================================

INSERT INTO Domain
SELECT SPLIT_PART("value"."PK"."S"::VARCHAR,'#',1) as DomainID,
       "value"."DomainNM"."S"::VARCHAR as DomainNM,
       "value"."Description"."S"::VARCHAR as Description,
       GETDATE() as load_timestamp
FROM dbagent.public."AgentTable"
WHERE "value"."EntityType"."S" = 'Domain';


INSERT INTO Agent
SELECT "value"."GSI1_PK"."S"::VARCHAR as DomainID,
       "value"."PK"."S"::VARCHAR as AgentID,
       "value"."AgentNM"."S"::VARCHAR as AgentNM,
       "value"."Score"."N"::INTEGER as Score,
       "value"."Description"."S"::VARCHAR as Description,
       GETDATE() as load_timestamp
FROM dbagent.public."AgentTable"
WHERE "value"."EntityType"."S" = 'Agent';


INSERT INTO Tool
SELECT "value"."GSI1_PK"."S"::VARCHAR as DomainID,
       "value"."PK"."S"::VARCHAR as AgentID,
       "value"."SK"."S"::VARCHAR as ToolID,
       "value"."ToolNM"."S"::VARCHAR as ToolNM,
       "value"."ToolSpec"."S"::VARCHAR as ToolSpec,
       "value"."Description"."S"::VARCHAR as Description,
       GETDATE() as load_timestamp
FROM dbagent.public."AgentTable"
WHERE "value"."EntityType"."S" = 'Tool';


INSERT INTO UserInfo
SELECT "value"."PK"."S"::VARCHAR as UserID,
       "value"."UserNM"."S"::VARCHAR as UserNM,
       "value"."UserProfile"."S"::VARCHAR as UserProfile,
       "value"."LastLoginDT"."S"::VARCHAR as LastLoginDT,
       "value"."CreationDT"."S"::VARCHAR as CreationDT,
GETDATE() as load_timestamp
FROM dbagent.public."AgentTable"
WHERE "value"."EntityType"."S" = 'UserInfo';


INSERT INTO UserSession
SELECT "value"."PK"."S"::VARCHAR as UserID,
       "value"."SK"."S"::VARCHAR as SessionID,
       "value"."UserSessionNM"."S"::VARCHAR as SessionNM,
       "value"."SessionSummary"."S"::VARCHAR as SessionSummary,
       "value"."SessionStartDT"."S"::VARCHAR as SessionStartDT,
       "value"."DtlFileLoc"."S"::VARCHAR as DtlFileLoc,
       GETDATE() as load_timestamp
FROM dbagent.public."AgentTable"
WHERE "value"."EntityType"."S" = 'UserSession';


INSERT INTO UserSessionProcess
SELECT SPLIT_PART("value"."PK"."S"::VARCHAR,'#',1) as UserID,
       SPLIT_PART("value"."PK"."S"::VARCHAR,'#',2) as SessionID,
       "value"."SK"."S"::VARCHAR as ProcessID,
       "value"."UserPrompt"."S"::VARCHAR as UserPrompt,
       "value"."ProcNM"."S"::VARCHAR as ProcNM,
       "value"."ProcDesc"."S"::VARCHAR as ProcDesc,
       "value"."ProcDT"."S"::VARCHAR as ProcDT,
       GETDATE() as load_timestamp
FROM dbagent.public."AgentTable"
WHERE "value"."EntityType"."S" = 'UserSessionProcess';


INSERT INTO user_tool_mapping_hist
SELECT SPLIT_PART("value"."PK"."S"::VARCHAR,'#',1) as UserID,
       SPLIT_PART("value"."PK"."S"::VARCHAR,'#',2) as SessionID,
       SPLIT_PART("value"."SK"."S"::VARCHAR,'#',1) as ProcessID,
       SPLIT_PART("value"."SK"."S"::VARCHAR,'#',2) as AgentID,
       SPLIT_PART("value"."SK"."S"::VARCHAR,'#',3) as ToolID,
       "value"."ToolNM"."S"::VARCHAR as ToolNM,
       "value"."ToolValues"."S"::VARCHAR as ToolValues,
       "value"."TransactDT"."S"::VARCHAR as TransactDT,
       "value"."SuccYN"."S"::VARCHAR as SuccYN,
       "value"."ResultMsg"."S"::VARCHAR as ResultMsg,
       GETDATE() as load_timestamp
FROM dbagent.public."AgentTable"
WHERE "value"."EntityType"."S" = 'UserSessPrcToolMappHist';


-- =====================================================
-- 3. ETL 프로세스 실행
-- =====================================================

-- 3-1. 원본 데이터를 스테이징 테이블로 변환
INSERT INTO agent_tool_analysis_staging (
    UserID, SessionID, ProcessID, DomainID, AgentID, ToolID, ToolNM,
    execution_date, execution_datetime, success_flag, tool_values, result_message
)
SELECT 
    h.UserID,
    h.SessionID,
    h.ProcessID, 
    a.DomainID,
    h.AgentID,
    h.ToolID,
    h.ToolNM,
    TO_DATE(LEFT(TransactDT, 8), 'YYYYMMDD') as execution_date,
    TO_TIMESTAMP(TransactDT, 'YYYYMMDDHH24MISS') as execution_datetime,
    CASE WHEN SuccYN = 'Y' THEN TRUE ELSE FALSE END as success_flag,
    h.ToolValues,
    h.ResultMsg as result_message
FROM user_tool_mapping_hist h,
     agent a 
WHERE h.AgentID = a.AgentID;

-- 3-2. 에이전트별 스코어 계산 및 업데이트
INSERT INTO agent_score_summary (
    DomainID, AgentID, AgentNM, total_executions, success_count, failure_count,
    success_rate, last_execution_date, days_since_last_exec, time_decay_factor, calculated_score
)
WITH agent_session_success AS (
    SELECT 
        h.UserID,
        h.SessionID,
        h.DomainID,
        h.AgentID,
        MAX(h.execution_date) as execution_date,
        -- 세션 내 해당 에이전트의 모든 툴이 성공해야 에이전트 실행 성공
        CASE WHEN MIN(CASE WHEN h.success_flag THEN 1 ELSE 0 END) = 1 
             THEN TRUE ELSE FALSE END as agent_success
    FROM agent_tool_analysis_staging h
    GROUP BY h.UserID, h.SessionID, h.DomainID, h.AgentID
)
SELECT 
    s.DomainID,
    s.AgentID,
    a.AgentNM,
    COUNT(*) as total_executions,
    SUM(CASE WHEN s.agent_success THEN 1 ELSE 0 END) as success_count,
    SUM(CASE WHEN NOT s.agent_success THEN 1 ELSE 0 END) as failure_count,
    CAST(SUM(CASE WHEN s.agent_success THEN 1 ELSE 0 END) AS DECIMAL) / COUNT(*) as success_rate,
    MAX(s.execution_date) as last_execution_date,
    DATEDIFF(day, MAX(s.execution_date), GETDATE()) as days_since_last_exec,
    EXP(-0.1 * DATEDIFF(day, MAX(s.execution_date), GETDATE())) as time_decay_factor,
    -- 스코어 공식: 총실행건수 × exp{-0.1 ×(오늘일시-최근실행일시)} × (성공건수/실행건수)²
    COUNT(*) * EXP(-0.1 * DATEDIFF(day, MAX(s.execution_date), GETDATE())) * 
    POWER(CAST(SUM(CASE WHEN s.agent_success THEN 1 ELSE 0 END) AS DECIMAL) / COUNT(*), 2) as calculated_score
FROM agent_session_success s
JOIN Agent a ON a.DomainID = s.DomainID AND a.AgentID = s.AgentID
GROUP BY s.DomainID, s.AgentID, a.AgentNM;


-- 3-3. 사용자별 에이전트 패턴 분석 (에이전트 단위 성공 기준)
INSERT INTO user_process_patterns (
    UserID, process_pattern, agent_sequence, tool_sequence, execution_count, success_count,
    first_used_date, last_used_date, pattern_score
)
SELECT 
    UserID,
    process_pattern,
    AgentID as agent_sequence,
    tool_sequence,
    COUNT(*) as execution_count,
    SUM(CASE WHEN agent_success THEN 1 ELSE 0 END) as success_count,
    MIN(first_used_date) as first_used_date,
    MAX(last_used_date) as last_used_date,
    -- 패턴 스코어 계산
    COUNT(*) * 
    POWER(CAST(SUM(CASE WHEN agent_success THEN 1 ELSE 0 END) AS DECIMAL) / COUNT(*), 2) *
    EXP(-0.05 * DATEDIFF(day, MAX(last_used_date), GETDATE())) as pattern_score
FROM (
    SELECT 
        UserID,
        AgentID,
        LISTAGG(ProcessID, '->') WITHIN GROUP (ORDER BY execution_datetime) as process_pattern,
        LISTAGG(ToolNM, '->') WITHIN GROUP (ORDER BY execution_datetime) as tool_sequence,
        -- 세션 내 해당 에이전트의 모든 툴이 성공해야 에이전트 실행 성공
        CASE WHEN MIN(CASE WHEN success_flag THEN 1 ELSE 0 END) = 1 
             THEN TRUE ELSE FALSE END as agent_success,
        MIN(execution_date) as first_used_date,
        MAX(execution_date) as last_used_date
    FROM agent_tool_analysis_staging
    GROUP BY UserID, AgentID, SessionID
) agent_sessions
GROUP BY UserID, process_pattern, AgentID, tool_sequence;

-- 3-4. 추천 패턴 업데이트 (상위 80% 패턴을 추천으로 마킹)
UPDATE user_process_patterns 
SET is_recommended = TRUE
WHERE pattern_score >= (
    SELECT PERCENTILE_CONT(0.8) WITHIN GROUP (ORDER BY pattern_score)
    FROM user_process_patterns
);

-- =====================================================
-- 4. 결과 확인 쿼리
-- =====================================================

-- 4-1. 에이전트 스코어 랭킹
SELECT 
    '=== 에이전트 스코어 랭킹 ===' as title,
    '' as DomainID, '' as AgentID, '' as agent_name, 
    NULL as total_executions, NULL as success_rate, NULL as calculated_score, NULL as score_rank
UNION ALL
SELECT 
    '' as title,
    DomainID,
    AgentID,
    AgentNM,
    total_executions,
    success_rate,
    calculated_score,
    RANK() OVER (PARTITION BY DomainID ORDER BY calculated_score DESC) as score_rank
FROM agent_score_summary
ORDER BY title DESC, calculated_score DESC;

-- 4-2. 사용자별 추천 에이전트 패턴
SELECT 
    '=== 사용자별 추천 에이전트 패턴 ===' as title,
    '' as UserID, '' as agent_sequence, 0 as pattern_score, '' as recommendation_status
UNION ALL
SELECT 
    '' as title,
    UserID,
    agent_sequence,
    pattern_score,
    CASE WHEN is_recommended THEN '추천' ELSE '일반' END as recommendation_status
FROM user_process_patterns
ORDER BY title DESC, pattern_score DESC;

-- 4-3. 에이전트 툴 에러 집계 
WITH agent_totals AS (
    SELECT AgentID, COUNT(*) as total_executions
    FROM agent_tool_analysis_staging
    GROUP BY AgentID
),
agent_errors AS (
    SELECT AgentID, COUNT(*) as total_errors,
           LISTAGG(DISTINCT ToolNM, ', ') WITHIN GROUP (ORDER BY ToolNM) as failed_tools
    FROM agent_tool_analysis_staging
    WHERE success_flag = FALSE
    GROUP BY AgentID
)
SELECT 
    '=== 에이전트별 에러 패턴 요약 ===' as title,
    NULL as AgentID, NULL as agent_name, NULL as total_errors, 
    NULL as error_rate, NULL as common_error_pattern
UNION ALL
SELECT '' as title, 
    e.AgentID,
    a.AgentNM as agent_name,
    e.total_errors,
    CAST(e.total_errors AS DECIMAL) / t.total_executions as error_rate,
    e.failed_tools
FROM agent_errors e
JOIN agent_totals t ON e.AgentID = t.AgentID
JOIN Agent a ON a.AgentID = e.AgentID
ORDER BY title desc , total_errors desc, error_rate DESC;
