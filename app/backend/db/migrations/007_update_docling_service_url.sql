-- app_settings의 docling_service_url을 b2 GPU 서버(192.168.1.82)로 업데이트
UPDATE app_settings SET value = 'http://192.168.1.82:28182' WHERE key = 'docling_service_url';
