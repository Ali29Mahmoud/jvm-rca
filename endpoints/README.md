# API Endpoints Summary (API Gateway)

All client requests are routed through the **API Gateway**:
- **Port-forward command**:
  ```bash
  kubectl port-forward svc/api-gateway-service -n eventuate-tram-examples-customers-and-orders 8080:8080
  ```
- **Gateway Base URL**: `http://localhost:8080`

---

## 1. Customer Service (via Gateway: `http://localhost:8080`)

### 1.1 Create Customer
- **Method**: `POST`
- **Endpoint**: `/customers`
- **Headers**: `Content-Type: application/json`
- **Request Body**:
  ```json
  {
    "name": "John Doe",
    "creditLimit": {
      "amount": 1000
    }
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "customerId": 1
  }
  ```

### 1.2 Get All Customers
- **Method**: `GET`
- **Endpoint**: `/customers`
- **Response**: `200 OK`
  ```json
  {
    "customers": [
      {
        "id": 1,
        "name": "John Doe",
        "creditLimit": {
          "amount": 1000
        }
      }
    ]
  }
  ```

### 1.3 Get Customer by ID
- **Method**: `GET`
- **Endpoint**: `/customers/{customerId}`
- **Response**: `200 OK` / `404 Not Found`

---

## 2. Order Service (via Gateway: `http://localhost:8080`)

### 2.1 Create Order (Triggers Saga)
- **Method**: `POST`
- **Endpoint**: `/orders`
- **Headers**: `Content-Type: application/json`
- **Request Body**:
  ```json
  {
    "customerId": 1,
    "orderTotal": {
      "amount": 150
    }
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "orderId": 1
  }
  ```

### 2.2 Get Order by ID
- **Method**: `GET`
- **Endpoint**: `/orders/{orderId}`
- **Response**: `200 OK`
  ```json
  {
    "orderId": 1,
    "orderState": "APPROVED",
    "rejectionReason": null
  }
  ```
  *(Possible states: `PENDING`, `APPROVED`, `REJECTED`, `CANCELLED`)*

### 2.3 Get All Orders
- **Method**: `GET`
- **Endpoint**: `/orders`
- **Response**: `200 OK`

---

## 3. Order History Service (CQRS) (via Gateway: `http://localhost:8080`)

### 3.1 Get Customer Order History
- **Method**: `GET`
- **Endpoint**: `/customers/{customerId}/orderhistory`
- **Response**: `200 OK` (retrieved from MongoDB)
  ```json
  {
    "id": 1,
    "name": "John Doe",
    "creditLimit": {
      "amount": 1000
    },
    "orders": {
      "1": {
        "orderId": 1,
        "orderTotal": {
          "amount": 150
        },
        "state": "APPROVED"
      }
    }
  }
  ```
