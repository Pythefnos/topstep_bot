import logging
import requests

logger = logging.getLogger(__name__)

class APIError(Exception):
    """Custom exception for API errors."""
    pass

class TopstepAPI:
    """
    Broker API interface for TopstepX (ProjectX) trading.
    Handles authentication, market data retrieval, and order placement.
    """
    def __init__(self, username: str, api_key: str, base_url: str, account_id: int, symbol: str, point_value: float = None):
        """
        Initialize the API client with user credentials and target symbol.
        """
        self.username = username
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')  # ensure no trailing slash
        self.account_id = account_id
        self.symbol_input = symbol  # symbol or contract identifier provided by user
        self.symbol_id = None       # will hold the resolved contract ID (if applicable)
        self.point_value = point_value  # monetary value per 1.0 price move, may be resolved later
        self.session = requests.Session()
        self.session_token = None

    def connect(self):
        """
        Authenticate with the TopstepX API and prepare for trading.
        Also resolves the symbol to a contract ID and tick parameters.
        """
        if not self.username or not self.api_key:
            raise APIError("API credentials (username/api_key) not provided.")

        # Step 1: Authenticate and get session token
        auth_url = f"{self.base_url}/api/Auth/loginKey"
        payload = {"userName": self.username, "apiKey": self.api_key}
        try:
            resp = self.session.post(auth_url, json=payload, timeout=10)
        except requests.RequestException as e:
            logger.error(f"Connection error during authentication: {e}")
            raise APIError("Failed to connect to TopstepX API for authentication.")
        if resp.status_code != 200:
            logger.error(f"Authentication failed: status {resp.status_code}, response: {resp.text}")
            raise APIError(f"Authentication failed with status code {resp.status_code}.")
        data = resp.json()
        if not data.get("success") or not data.get("token"):
            logger.error(f"Authentication error: {data}")
            raise APIError("Authentication response did not contain a valid token.")
        # Store session token for future requests
        self.session_token = data["token"]
        self.session.headers.update({"Authorization": f"Bearer {self.session_token}"})
        logger.info("Authenticated with TopstepX API successfully.")

        # Step 2: Resolve symbol to contract ID (if necessary) and get contract details
        if self.symbol_input:
            try:
                self._resolve_symbol(self.symbol_input)
            except APIError as e:
                logger.error(f"Symbol resolution failed: {e}")
                raise
        else:
            raise APIError("No trading symbol provided in configuration.")

    def _resolve_symbol(self, symbol: str):
        """
        Resolve a user-provided symbol (or contract code) to the specific contract ID required by the API.
        Updates self.symbol_id and self.point_value using contract details from API.
        """
        if symbol.startswith("CON."):
            # Already a contract ID
            self.symbol_id = symbol
            # Fetch contract info to get tick value if needed
            contract_info = self._fetch_contract_by_id(symbol)
        else:
            # Search for contracts matching the symbol text
            search_url = f"{self.base_url}/api/Contract/search"
            payload = {"searchText": symbol, "live": False}
            try:
                resp = self.session.post(search_url, json=payload, timeout=5)
            except requests.RequestException as e:
                raise APIError(f"Contract search request failed: {e}")
            if resp.status_code != 200:
                raise APIError(f"Contract search failed with status code {resp.status_code}.")
            result = resp.json()
            if not result.get("success") or "contracts" not in result:
                raise APIError(f"Contract search did not return results for symbol '{symbol}'.")
            contracts = result["contracts"]
            if len(contracts) == 0:
                raise APIError(f"No contract found for symbol search '{symbol}'.")
            # If multiple results, attempt to pick the intended contract
            selected = None
            symbol_upper = symbol.upper()
            if len(contracts) == 1:
                selected = contracts[0]
            else:
                # Try exact name match
                for c in contracts:
                    if c.get("name", "").upper() == symbol_upper:
                        selected = c
                        break
                if selected is None:
                    # If symbol likely refers to e-mini vs micro, pick based on 'M' prefix or tick value
                    if symbol_upper.startswith('M'):
                        # User likely intended a Micro contract
                        selected = min(contracts, key=lambda c: c.get("tickValue", 0))
                    else:
                        # Default to contract with largest tick value (likely the full-sized contract)
                        selected = max(contracts, key=lambda c: c.get("tickValue", 0))
                    logger.info(f"Multiple contracts found for '{symbol}'. Selected '{selected.get('name')}' by tickValue heuristic.")
            if selected is None:
                raise APIError(f"Ambiguous symbol '{symbol}'. Please specify a full contract code.")
            self.symbol_id = selected.get("id")
            contract_info = selected  # we already have details in search result

        if self.symbol_id:
            logger.info(f"Resolved trading symbol '{symbol}' to contract ID '{self.symbol_id}'.")
        # Set point_value if not already set in config
        if contract_info:
            tick_size = contract_info.get("tickSize")
            tick_val = contract_info.get("tickValue")
            if tick_size is not None and tick_val is not None:
                calculated_point_value = tick_val / tick_size
                if self.point_value is None:
                    self.point_value = calculated_point_value
                else:
                    # If config provided a point_value, we could verify it against calculated
                    if abs(self.point_value - calculated_point_value) > 1e-6:
                        logger.info(f"Config point_value ({self.point_value}) differs from contract data ({calculated_point_value:.2f}). Using config value.")
            # If account starting balance can be fetched from contract or account info, do separately (not here).
        else:
            logger.warning("Contract information could not be retrieved for symbol resolution.")

    def _fetch_contract_by_id(self, contract_id: str) -> dict:
        """Fetch contract details by contract ID (returns contract info including tick parameters)."""
        url = f"{self.base_url}/api/Contract/searchById"
        payload = {"contractId": contract_id}
        try:
            resp = self.session.post(url, json=payload, timeout=5)
        except requests.RequestException as e:
            raise APIError(f"Contract lookup failed: {e}")
        if resp.status_code != 200:
            raise APIError(f"Contract lookup failed with status code {resp.status_code}.")
        data = resp.json()
        if not data.get("success") or "contracts" not in data or len(data["contracts"]) == 0:
            raise APIError(f"Contract ID {contract_id} not found.")
        return data["contracts"][0]

    def get_latest_price(self):
        """
        Retrieve the latest market price for the configured symbol (contract).
        Returns the price as a float.
        """
        if not self.symbol_id:
            raise APIError("Symbol/contract not resolved. Cannot fetch price.")
        # For simplicity, use a contract search (bars or quote) to get last price.
        # Here we call the contract search again which also provides some details.
        # A better approach is to use real-time WebSocket or a specific quote endpoint.
        url = f"{self.base_url}/api/Contract/searchById"
        payload = {"contractId": self.symbol_id}
        try:
            resp = self.session.post(url, json=payload, timeout=5)
        except requests.RequestException as e:
            raise APIError(f"Price fetch request failed: {e}")
        if resp.status_code != 200:
            # If token expired, try re-auth once
            if resp.status_code == 401:
                logger.warning("Session token expired, re-authenticating...")
                self.connect()  # re-auth and re-resolve symbol
                resp = self.session.post(url, json=payload, timeout=5)
                if resp.status_code != 200:
                    raise APIError(f"Price fetch failed after re-auth, status {resp.status_code}.")
            else:
                raise APIError(f"Failed to get price, status code {resp.status_code}.")
        data = resp.json()
        if not data.get("success") or "contracts" not in data:
            raise APIError("Invalid response when fetching price.")
        contracts = data["contracts"]
        if not contracts:
            raise APIError("No contract data in price response.")
        # Assuming the first (and only) contract returned is ours
        contract = contracts[0]
        price = None
        # Try to get a price field; the API might include fields like "lastPrice" or "bid"/"ask".
        if "lastPrice" in contract:
            price = contract["lastPrice"]
        elif "last" in contract:
            price = contract["last"]
        # If not present, the API might not provide price in this call.
        if price is None:
            # Optionally, could use a separate market data API to get a price tick
            raise APIError("Price not available in contract data.")
        return float(price)

    def place_order(self, symbol: str, side: str, size: int):
        """
        Place a market order for the given symbol (contract) and size.
        side: "buy" or "sell".
        """
        order_url = f"{self.base_url}/api/Order/place"
        # Determine side code as per API (0 = buy/bid, 1 = sell/ask)
        side_code = 0 if side.lower() == "buy" else 1
        order_payload = {
            "accountId": self.account_id,
            "contractId": symbol,
            "type": 2,   # 2 = Market order
            "side": side_code,
            "size": size,
            "limitPrice": None,
            "stopPrice": None,
            "trailPrice": None,
            "customTag": None,
            "linkedOrderId": None
        }
        try:
            resp = self.session.post(order_url, json=order_payload, timeout=5)
        except requests.RequestException as e:
            raise APIError(f"Order placement request failed: {e}")
        if resp.status_code == 401:
            # Session might have expired, try re-auth once
            logger.warning("Session token possibly expired during order. Re-authenticating...")
            self.connect()
            try:
                resp = self.session.post(order_url, json=order_payload, timeout=5)
            except requests.RequestException as e:
                raise APIError(f"Order placement request failed after re-auth: {e}")
        if resp.status_code != 200:
            raise APIError(f"Order placement failed with status {resp.status_code}: {resp.text}")
        result = resp.json()
        if not result.get("success", False):
            err_msg = result.get("errorMessage") or "Unknown error"
            raise APIError(f"Order placement failed: {err_msg}")
        order_id = result.get("orderId")
        logger.debug(f"Order placed successfully. Order ID: {order_id}")
        return order_id

    def flatten_position(self, symbol: str, size: int, side: str):
        """
        Close/flatten an open position by placing a market order of given size on the opposite side.
        This is a convenience wrapper around place_order.
        """
        # 'side' parameter here should be the action to flatten: if current pos is long, side="sell"; if short, side="buy".
        return self.place_order(symbol=symbol, side=side, size=size)

    def get_starting_balance(self):
        """
        Optionally retrieve the account's starting balance (initial equity).
        In this implementation, returns None (could be extended to call an account API endpoint).
        """
        # TODO: Implement API call to retrieve account balance if available.
        return None
