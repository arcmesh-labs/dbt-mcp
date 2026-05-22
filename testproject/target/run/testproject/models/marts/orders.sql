
  
    
    

    create  table
      "testproject"."main"."orders__dbt_tmp"
  
    as (
      select * from "testproject"."main"."stg_orders"
    );
  
  