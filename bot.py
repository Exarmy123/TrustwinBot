-- Supabase SQL Editor में
CREATE OR REPLACE FUNCTION increment_daily_ticket(
    user_id_input BIGINT,
    ticket_date_input DATE,
    num_tickets_to_add INT DEFAULT 1 -- नया पैरामीटर
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO daily_tickets (telegram_id, date, count)
    VALUES (user_id_input, ticket_date_input, num_tickets_to_add)
    ON CONFLICT (telegram_id, date) DO UPDATE
    SET count = daily_tickets.count + EXCLUDED.count;
END;
$$ LANGUAGE plpgsql;
