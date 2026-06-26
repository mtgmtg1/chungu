-- Add language preference column to users table for i18n support
ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en';

UPDATE users SET language = 'en' WHERE language IS NULL;
