-- 비디오 초당 포인트 비용을 10원으로 일괄 업데이트
INSERT INTO app_settings (key, value, encrypted)
VALUES ('cost_per_video_sec_krw', '10', 0)
ON CONFLICT (key) DO UPDATE SET value = '10', encrypted = 0;
