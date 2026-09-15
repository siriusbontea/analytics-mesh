SELECT product, SUM(amount) AS total
FROM sales
GROUP BY product
ORDER BY total DESC
