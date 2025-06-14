import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

class APIError(Exception):
    """Custom exception for API errors."""
    pass

class TopstepAPI:
    """
    Broker API interface for TopstepX (ProjectX) trading.
    Handles authentication, market data retrieval, and order placement.
    """
    def __init__(self, username: str, api_key: str, base_url: str, account_id: int,
                 symbol: str, point_value: float = None):
        """
        Initialize the API client with user credentials and target symbol.
        """
        self.username = username
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')  # ensure no trailing slash
        self.account_id = account_id
        self.symbol_input = symbol    # symbol or contract code provided by user

        self.symbol_id = None         # resolved contract ID (set after connect)
        self.point_value = point_value  # monetary value per 1.0 price move (set after connect if None)
        self.session = requests.Session()
        self.session_token = None

    def connect(self) -> None:
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
        try:
            data = resp.json()
        except ValueError as e:
            logger.error(f"Authentication response JSON parse failed: {e}")
            raise APIError("Authentication response did not contain valid JSON.")
        if not data.get("success") or not data.get("token"):
            logger.error(f"Authentication error: {data}")
            raise APIError("Authentication response did not contain a valid token.")
        # Store session token for future requests
        self.session_token = data["token"]
        self.session.headers.update({"Authorization": f"Bearer {self.session_token}"})
        logger.info("Authenticated with TopstepX API successfully.")

        # Step 2: Resolve symbol to contract ID and set contract parameters
        if self.symbol_input:
            self._resolve_symbol(self.symbol_input)
        else:
            raise APIError("No trading symbol provided in configuration.")

    def _resolve_symbol(self, symbol: str) -> None:
        """
        Resolve a user-provided symbol (or contract code) to the specific contract ID required by the API.
        Updates self.symbol_id and self.point_value using contract details from the API.
        """
        if symbol.startswith("CON."):
            # Already provided a contract ID
            self.symbol_id = symbol
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
            try:
                result = resp.json()
            except ValueError as e:
                raise APIError(f"Contract search response parse failed: {e}")
            if not result.get("success") or "contracts" not in result:
                raise APIError(f"Contract search did not return results for symbol '{symbol}'.")
            contracts = result.get("contracts", [])
            if len(contracts) == 0:
                raise APIError(f"No contract found for symbol '{symbol}'.")
            # If multiple results, pick best match (prefer exact match or use tick value heuristic for e-mini vs micro)
            selected = None
            symbol_up = symbol.upper()
            if len(contracts) == 1:
                selected = contracts[0]
            else:
                # Try exact name match first
                for c in contracts:
                    if c.get("name", "").upper() == symbol_up:
                        selected = c
                        break
                if selected is None:
                    # If symbol refers to micro vs e-mini, choose based on tick value (micro has smaller tickValue)
                    if symbol_up.startswith('M'):
                        selected = min(contracts, key=lambda c: c.get("tickValue", 0))
                    else:
                        selected = max(contracts, key=lambda c: c.get("tickValue", 0))
                    logger.info(f"Multiple contracts found for '{symbol}'. Selected '{selected.get('name')}' by tick value heuristic.")
            if selected is None:
                raise APIError(f"Ambiguous symbol '{symbol}'. Please specify a full contract code.")
            self.symbol_id = selected.get("id")
            contract_info = selected

        if self.symbol_id:
            logger.info(f"Resolved trading symbol '{symbol}' to contract ID '{self.symbol_id}'.")
        # Use contract info to set point_value if not provided in config
        if contract_info:
            tick_size = contract_info.get("tickSize")
            tick_val = contract_info.get("tickValue")
            if tick_size is not None and tick_val is not None:
                calculated_pv = tick_val / tick_size
                if self.point_value is None:
                    self.point_value = calculated_pv
                elif abs(self.point_value - calculated_pv) > 1e-6:
                    logger.info(f"Config point_value ({self.point_value}) differs from contract data ({calculated_pv:.2f}). Using config value.")
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
        try:
            data = resp.json()
        except ValueError as e:
            raise APIError(f"Contract lookup response parse failed: {e}")
        if not data.get("success") or "contracts" not in data or len(data.get("contracts", [])) == 0:
            raise APIError(f"Contract ID {contract_id} not found.")
        return data["contracts"][0]

    def get_latest_price(self) -> float:
        """
        Retrieve the latest market price for the resolved contract.
        Returns the price as a float.
        """
        if not self.symbol_id:
            raise APIError("Symbol not resolved. Cannot fetch price.")
        url = f"{self.base_url}/api/Contract/searchById"
        payload = {"contractId": self.symbol_id}
        try:
            resp = self.session.post(url, json=payload, timeout=5)
        except requests.RequestException as e:
            raise APIError(f"Price fetch request failed: {e}")
        if resp.status_code != 200:
            if resp.status_code == 401:
                logger.warning("Session token expired, re-authenticating...")
                self.connect()  # re-authenticate and retry
                resp = self.session.post(url, json=payload, timeout=5)
                if resp.status_code != 200:
                    raise APIError(f"Price fetch failed after re-auth, status {resp.status_code}: {resp.text}")
            else:
                raise APIError(f"Failed to get price, status code {resp.status_code}: {resp.text}")
        try:
            data = resp.json()
        except ValueError as e:
            raise APIError(f"Invalid price data response: {e}")
        if not data.get("success") or "contracts" not in data:
            raise APIError("Invalid response structure when fetching price.")
        contracts = data["contracts"]
        if not contracts:
            raise APIError("No contract data in price response.")
        contract = contracts[0]
        price = contract.get("lastPrice") if "lastPrice" in contract else contract.get("last")
        if price is None:
            raise APIError("Price not available in contract data.")
        return float(price)

    def place_order(self, symbol: str, side: str, size: int) -> str:
        """
        Place a market order for the given contract symbol and size.
        side: "buy" or "sell".
        Returns the order ID on success.
        """
        order_url = f"{self.base_url}/api/Order/place"
        side_code = 0 if side.lower() == "buy" else 1
        order_payload = {
            "accountId": self.account_id,
            "contractId": symbol,
            "type": 2,  # Market order
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
            # Session might have expired – try one reconnect
            logger.warning("Session token expired during order. Re-authenticating...")
            self.connect()
            try:
                resp = self.session.post(order_url, json=order_payload, timeout=5)
            except requests.RequestException as e:
                raise APIError(f"Order placement request failed after re-auth: {e}")
        if resp.status_code != 200:
            raise APIError(f"Order placement failed with status {resp.status_code}: {resp.text}")
        try:
            result = resp.json()
        except ValueError as e:
            raise APIError(f"Order placement response parse failed: {e}")
        if not result.get("success", False):
            err_msg = result.get("errorMessage") or "Unknown error"
            raise APIError(f"Order placement failed: {err_msg}")
        order_id = result.get("orderId")
        logger.debug(f"Order placed successfully. Order ID: {order_id}")
        return str(order_id)

    def flatten_position(self, symbol: str, size: int, side: str) -> str:
        """
        Flatten an open position by placing a market order of the given size on the opposite side.
        Returns the new order ID.
        """
        return self.place_order(symbol=symbol, side=side, size=size)

    def get_starting_balance(self) -> Optional[float]:
        """
        Retrieve the account's starting balance (initial equity).
        (Not implemented in the API - returns None. Use config 'starting_balance' for Combine accounts.)
        """
        return None
