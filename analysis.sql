-- Synthetic Product Growth Learning Lab
-- Source table: product_growth, loaded from sample-product-growth.csv

-- Weekly funnel, revenue, and support summary.
SELECT
  week_start,
  SUM(signups) AS signups,
  SUM(activated_users) AS activated_users,
  ROUND(1.0 * SUM(activated_users) / SUM(signups), 4) AS activation_rate,
  SUM(paid_conversions) AS paid_conversions,
  ROUND(1.0 * SUM(paid_conversions) / SUM(signups), 4) AS signup_to_paid_rate,
  SUM(revenue_usd) AS revenue_usd,
  SUM(support_tickets) AS support_tickets,
  ROUND(100.0 * SUM(support_tickets) / SUM(signups), 2) AS tickets_per_100_signups
FROM product_growth
GROUP BY week_start
ORDER BY week_start;

-- First-to-last-week change by acquisition channel.
WITH channel_baselines AS (
  SELECT
    acquisition_channel,
    MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN signups END) AS first_signups,
    MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN signups END) AS last_signups,
    1.0 * MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN activated_users END)
      / MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN signups END) AS first_activation_rate,
    1.0 * MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN activated_users END)
      / MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN signups END) AS last_activation_rate,
    1.0 * MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN paid_conversions END)
      / MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN signups END) AS first_paid_rate,
    1.0 * MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN paid_conversions END)
      / MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN signups END) AS last_paid_rate,
    MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN revenue_usd END) AS first_revenue,
    MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN revenue_usd END) AS last_revenue,
    MAX(CASE WHEN week_start = (SELECT MIN(week_start) FROM product_growth)
      THEN support_tickets END) AS first_tickets,
    MAX(CASE WHEN week_start = (SELECT MAX(week_start) FROM product_growth)
      THEN support_tickets END) AS last_tickets
  FROM product_growth
  GROUP BY acquisition_channel
)
SELECT
  acquisition_channel,
  first_signups,
  last_signups,
  ROUND(1.0 * last_signups / first_signups - 1, 4) AS signup_growth,
  ROUND(first_activation_rate, 4) AS first_activation_rate,
  ROUND(last_activation_rate, 4) AS last_activation_rate,
  ROUND(last_activation_rate - first_activation_rate, 4) AS activation_rate_change,
  ROUND(100.0 * (last_activation_rate - first_activation_rate), 2) AS activation_rate_change_pp,
  ROUND(first_paid_rate, 4) AS first_paid_rate,
  ROUND(last_paid_rate, 4) AS last_paid_rate,
  ROUND(last_paid_rate - first_paid_rate, 4) AS paid_rate_change,
  ROUND(100.0 * (last_paid_rate - first_paid_rate), 2) AS paid_rate_change_pp,
  first_revenue,
  last_revenue,
  ROUND(1.0 * last_revenue / first_revenue - 1, 4) AS revenue_growth,
  first_tickets,
  last_tickets,
  ROUND(1.0 * last_tickets / first_tickets - 1, 4) AS ticket_growth
FROM channel_baselines
ORDER BY revenue_growth DESC;

-- Deterministic preview of the source grain.
SELECT
  week_start,
  acquisition_channel,
  signups,
  activated_users,
  paid_conversions,
  revenue_usd,
  support_tickets
FROM product_growth
ORDER BY week_start, acquisition_channel
LIMIT 10;
