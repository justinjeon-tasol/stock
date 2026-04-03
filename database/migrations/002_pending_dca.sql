CREATE TABLE IF NOT EXISTS pending_dca (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  position_id uuid REFERENCES positions(id),
  code text NOT NULL,
  name text NOT NULL,
  stage int NOT NULL DEFAULT 2,
  target_price numeric NOT NULL,
  budget numeric NOT NULL,
  quantity int NOT NULL,
  status text NOT NULL DEFAULT 'PENDING',
  created_at timestamptz DEFAULT now(),
  expires_at timestamptz NOT NULL,
  executed_at timestamptz
);
