-- DBAgent 테이블 데이터 삽입 스크립트
-- 도메인, 에이전트, 툴, 사용자, 세션 및 프로세스 툴 매핑 이력 데이터

-- 도메인 데이터
INSERT INTO DBAgent (pk, sk, entity_type, domain_nm, description) VALUES
('DMN001', 'METADATA', 'Domain', '매장검색서비스', '지역 기반의 매장 검색 서비스로 사용자가 요청한 지역의 카페, 레스토랑을 다양한 카테고리별로 검색하여 찾아주는 서비스');

-- 에이전트 데이터
INSERT INTO DBAgent (pk, sk, entity_type, agent_nm, score, description) VALUES
('AGT001', 'METADATA', 'Agent', '매장 검색 에이전트', 60, '지역기반 매장 검색서비스로 최근매장 리스트업이 잘되있음'),
('AGT002', 'METADATA', 'Agent', '매장 검색 에이전트2', 40, '지역 기반 매장 검색 및 추천 서비스 제공'),
('AGT003', 'METADATA', 'Agent', '매장 검색 에이전트3', 50, '동네 매장 검색 추천 서비스');

-- 툴 데이터
INSERT INTO DBAgent (pk, sk, entity_type, tool_nm, tool_spec, description) VALUES
('AGT001', 'TL001', 'Tool', 'FIND_LOC', '{"description": "특정 지역 검색", "parameters": {"location": "string", "radius": "string"}}', '특정지역주변의 매장을 검색하는 도구'),
('AGT001', 'TL002', 'Tool', 'USE_SEARCH_ENGINE_API', '{"description": "검색엔진의 API 호출", "parameters": {"location": "string", "radius": "string", "cuisine": "string"}}', '위치값,반경등을 받아 검색엔진의 API를 순차적으로 검색'),
('AGT001', 'TL003', 'Tool', 'FORMAT_RESULTS', '{"description": "결과를 리스트형태로 전달", "parameters": {"results": "string"}}', '결과값을 포맷팅하여 리스트형태로 전달'),
('AGT002', 'TL001', 'Tool', 'FIND_LOC', '{"description": "특정 지역 검색", "parameters": {"location": "string", "radius": "string"}}', '특정지역주변의 매장을 검색하는 도구'),
('AGT002', 'TL002', 'Tool', 'USE_SEARCH_ENGINE_API', '{"description": "검색엔진의 API 호출", "parameters": {"location": "string", "radius": "string", "cuisine": "string"}}', '위치값,반경등을 받아 검색엔진의 API를 순차적으로 검색'),
('AGT002', 'TL003', 'Tool', 'FORMAT_RESULTS', '{"description": "결과를 리스트형태로 전달", "parameters": {"results": "string"}}', '결과값을 포맷팅하여 리스트형태로 전달');

-- 사용자 데이터
INSERT INTO DBAgent (pk, sk, entity_type, user_nm, user_profile, last_login_dt, creation_dt) VALUES
('USR001', 'METADATA', 'User', '돌칼', '{"birth":"19741126","HP":"010-2222-3333","ADDR":"서울시 송파구 잠실동","age":"51"}', '2025061414100223', '20250601093210'),
('USR002', 'METADATA', 'User', '김철수', '{"birth":"19850315","HP":"010-3333-4444","ADDR":"서울시 강남구 역삼동","age":"39"}', '20250614150000', '20250601100000'),
('USR003', 'METADATA', 'User', '이영희', '{"birth":"19920720","HP":"010-5555-6666","ADDR":"서울시 마포구 홍대동","age":"32"}', '20250614160000', '20250601110000');

-- 사용자 세션 데이터
INSERT INTO DBAgent (pk, sk, entity_type, user_session_nm, session_summary, session_start_dt, dtl_file_loc) VALUES
('USR001', 'SESS20250614001', 'UserSession', '잠실종합운동장 맛집 검색 세션', '잠실종합 운동장 주변 맛집 검색 및 추천', '20250614140530', 'S3://usersess/2025...'),
('USR002', 'SESS20250614002', 'UserSession', '강남역 맛집 검색 세션', '강남역 주변 맛집 검색 및 추천', '20250614150530', 'S3://usersess/2025...'),
('USR003', 'SESS20250614003', 'UserSession', '홍대 카페 검색 세션', '홍대 주변 카페 검색 및 추천', '20250614160530', 'S3://usersess/2025...');

-- 사용자 세션 프로세스 데이터
INSERT INTO DBAgent (pk, sk, entity_type, user_prompt, proc_nm, process_desc, proc_dt) VALUES
('USR001#SESS20250614001', 'PRC001', 'UserSessionProcess', '잠실종합운동장 근처에 있는 N매장 근처의 최근에 생긴 카페를 찾아줘', '위치확인', '먼저 잠실종합운동장의 위치를 확인한다.', '20250614140601'),
('USR001#SESS20250614001', 'PRC002', 'UserSessionProcess', '잠실종합운동장 근처에 있는 N매장 근처의 최근에 생긴 카페를 찾아줘', '매장검색', '잠실종합운동장 근처의 카페를 찾기 위해 검색엔진과 SNS의 API를 활용한다.', '20250614140601'),
('USR001#SESS20250614001', 'PRC003', 'UserSessionProcess', '잠실종합운동장 근처에 있는 N매장 근처의 최근에 생긴 카페를 찾아줘', '결과포맷팅', '검색한결과를 포맷팅해서 최종결과를 응답한다', '20250614140602'),
('USR002#SESS20250614002', 'PRC001', 'UserSessionProcess', '강남역 근처 맛집 찾아줘', '위치확인', '강남역의 위치를 확인한다.', '20250614150601'),
('USR002#SESS20250614002', 'PRC002', 'UserSessionProcess', '강남역 근처 맛집 찾아줘', '매장검색', '강남역 근처의 맛집을 검색한다.', '20250614150601'),
('USR002#SESS20250614002', 'PRC003', 'UserSessionProcess', '강남역 근처 맛집 찾아줘', '결과포맷팅', '검색한 맛집 결과를 포맷팅한다.', '20250614150602'),
('USR003#SESS20250614003', 'PRC001', 'UserSessionProcess', '홍대 카페 추천해줘', '위치확인', '홍대의 위치를 확인한다.', '20250614160601'),
('USR003#SESS20250614003', 'PRC002', 'UserSessionProcess', '홍대 카페 추천해줘', '매장검색', '홍대 근처의 카페를 검색한다.', '20250614160601'),
('USR003#SESS20250614003', 'PRC003', 'UserSessionProcess', '홍대 카페 추천해줘', '결과포맷팅', '검색한 카페 결과를 포맷팅한다.', '20250614160602');

-- 사용자 세션 프로세스 툴 매핑 이력 데이터
INSERT INTO DBAgent (pk, sk, entity_type, tool_nm, tool_values, transact_dt, succ_yn, result_msg) VALUES
('USR001#SESS20250614001', 'PRC001#AGT001#TL001','UserSessPrcToolMappHist', 'FIND_LOC', '잠실종합운동장 근처에 있는 N매장 근처의 최근에 생긴 카페를 찾아줘', '20250614140605', 'Y', '사용자의 요청, 잠실종합운동장 위치'),
('USR001#SESS20250614001', 'PRC002#AGT001#TL002','UserSessPrcToolMappHist', 'USE_SEARCH_ENGINE_API', '위 밸류값, 잠실종합운동장 위치, 네이버, 구글검색API', '20250614140606', 'Y', '카페리스트'),
('USR001#SESS20250614001', 'PRC003#AGT001#TL003','UserSessPrcToolMappHist', 'FORMAT_RESULTS', '맛집명단리스트, 포맷팅 템플릿 스크립트', '20250614140607', 'Y', '포맷된 카페리스트'),
('USR002#SESS20250614002', 'PRC001#AGT001#TL001','UserSessPrcToolMappHist', 'FIND_LOC', '강남역 근처 맛집 찾아줘', '20250614150605', 'Y', '강남역 위치 확인'),
('USR002#SESS20250614002', 'PRC002#AGT001#TL002','UserSessPrcToolMappHist', 'USE_SEARCH_ENGINE_API', '강남역, 맛집, 검색API', '20250614150606', 'Y', '맛집리스트'),
('USR002#SESS20250614002', 'PRC003#AGT001#TL003','UserSessPrcToolMappHist', 'FORMAT_RESULTS', '맛집리스트, 포맷팅', '20250614150607', 'N', '포맷팅 실패'),
('USR003#SESS20250614003', 'PRC001#AGT002#TL001','UserSessPrcToolMappHist', 'FIND_LOC', '홍대 카페 추천해줘', '20250614160605', 'Y', '홍대 위치 확인'),
('USR003#SESS20250614003', 'PRC002#AGT002#TL002','UserSessPrcToolMappHist', 'USE_SEARCH_ENGINE_API', '홍대, 카페, API호출', '20250614160606', 'Y', '카페목록'),
('USR003#SESS20250614003', 'PRC003#AGT002#TL003','UserSessPrcToolMappHist', 'FORMAT_RESULTS', '카페목록, 사용자친화적포맷', '20250614160607', 'Y', '포맷된 카페목록');