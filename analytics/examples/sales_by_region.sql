SELECT region, SUM(amount) AS total, COUNT(*) AS orders
FROM sales
GROUP BY region
ORDER BY total DESC
