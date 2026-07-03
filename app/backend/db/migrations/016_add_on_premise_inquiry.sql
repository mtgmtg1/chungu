CREATE TABLE IF NOT EXISTS on_premise_inquiries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    email VARCHAR(255) NOT NULL,
    company VARCHAR(255),
    contact_name VARCHAR(255),
    country VARCHAR(100),
    pages_per_hour INTEGER NOT NULL,
    estimated_price INTEGER NOT NULL,
    message TEXT,
    agreed_terms BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_on_premise_inquiries_user_id ON on_premise_inquiries(user_id);
CREATE INDEX IF NOT EXISTS idx_on_premise_inquiries_status ON on_premise_inquiries(status);
CREATE INDEX IF NOT EXISTS idx_on_premise_inquiries_created_at ON on_premise_inquiries(created_at DESC);
