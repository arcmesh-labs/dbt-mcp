with source as (
    select * from (
        values
            (1,  101, 49.99,  'completed'),
            (2,  102, 19.50,  'completed'),
            (3,  103, 89.00,  'pending'),
            (4,  101, 12.75,  'completed'),
            (5,  104, 200.00, 'shipped'),
            (6,  105, 5.00,   'completed'),
            (7,  102, 33.30,  'cancelled'),
            (8,  106, 77.77,  'completed'),
            (9,  107, 150.00, 'pending'),
            (10, 108, 60.00,  'shipped')
    ) as t(order_id, customer_id, amount, status)
)

select
    order_id,
    customer_id,
    amount,
    status
from source
