// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title MEFAI Risk Governor
 * @notice On-chain drawdown killswitch for an autonomous trading agent. The
 *         agent's executor records equity each cycle; if peak-to-trough drawdown
 *         breaches the budget the vault is HALTED and canTrade() returns false
 *         until the owner resumes it. This mirrors the off-chain drawdown-budget
 *         sizing so the disqualification-critical risk limit is enforced and
 *         provable on-chain, not only inside the agent's own code.
 * @dev Equity is a caller-defined fixed-point scale (e.g. USD cents). The keeper
 *      is the agent executor allowed to push equity; the owner can pause, resume,
 *      and re-tune the budget. canTrade() is the gate an executor checks before
 *      placing an order.
 */
contract RiskGovernor {
    uint16 public constant BPS = 10000;

    address public owner;
    address public keeper;
    bool public globalPaused;
    uint16 public maxDrawdownBps; // e.g. 1500 = 15%

    struct Vault {
        uint128 hwm;     // equity high-water mark
        uint128 equity;  // last recorded equity
        uint40 updatedAt;
        bool halted;
        bool registered;
    }

    mapping(address => Vault) public vaults;
    address[] public vaultList;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event KeeperSet(address indexed keeper);
    event MaxDrawdownSet(uint16 bps);
    event GlobalPauseSet(bool paused);
    event VaultRegistered(address indexed agent, uint256 initialEquity);
    event EquityRecorded(
        address indexed agent,
        uint256 equity,
        uint256 hwm,
        uint256 drawdownBps
    );
    event Halted(address indexed agent, uint256 drawdownBps);
    event Resumed(address indexed agent, uint256 equity);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier onlyKeeper() {
        require(msg.sender == keeper, "Not keeper");
        _;
    }

    constructor(uint16 _maxDrawdownBps) {
        require(_maxDrawdownBps > 0 && _maxDrawdownBps <= BPS, "Bad bps");
        owner = msg.sender;
        keeper = msg.sender;
        maxDrawdownBps = _maxDrawdownBps;
        emit OwnershipTransferred(address(0), msg.sender);
        emit KeeperSet(msg.sender);
    }

    // ----------------------------------------------------------------
    // Admin
    // ----------------------------------------------------------------

    function setKeeper(address _keeper) external onlyOwner {
        require(_keeper != address(0), "Zero address");
        keeper = _keeper;
        emit KeeperSet(_keeper);
    }

    function setMaxDrawdownBps(uint16 bps) external onlyOwner {
        require(bps > 0 && bps <= BPS, "Bad bps");
        maxDrawdownBps = bps;
        emit MaxDrawdownSet(bps);
    }

    function setGlobalPaused(bool value) external onlyOwner {
        globalPaused = value;
        emit GlobalPauseSet(value);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // ----------------------------------------------------------------
    // Vault lifecycle
    // ----------------------------------------------------------------

    function registerVault(address agent, uint256 initialEquity)
        external
        onlyKeeper
    {
        require(agent != address(0), "Zero address");
        Vault storage v = vaults[agent];
        require(!v.registered, "Already registered");
        require(initialEquity <= type(uint128).max, "Equity overflow");

        v.hwm = uint128(initialEquity);
        v.equity = uint128(initialEquity);
        v.updatedAt = uint40(block.timestamp);
        v.halted = false;
        v.registered = true;
        vaultList.push(agent);

        emit VaultRegistered(agent, initialEquity);
    }

    /// @notice Record the agent's latest equity. Updates the high-water mark and
    ///         halts the vault if drawdown from the peak breaches the budget.
    function recordEquity(address agent, uint256 equity) external onlyKeeper {
        Vault storage v = vaults[agent];
        require(v.registered, "Not registered");
        require(equity <= type(uint128).max, "Equity overflow");

        v.equity = uint128(equity);
        v.updatedAt = uint40(block.timestamp);
        if (equity > v.hwm) {
            v.hwm = uint128(equity);
        }

        uint256 dd = _drawdownBps(v.hwm, v.equity);
        if (dd >= maxDrawdownBps && !v.halted) {
            v.halted = true;
            emit Halted(agent, dd);
        }

        emit EquityRecorded(agent, equity, v.hwm, dd);
    }

    /// @notice Clear a halt and restart the drawdown window from current equity.
    function resume(address agent) external onlyOwner {
        Vault storage v = vaults[agent];
        require(v.registered, "Not registered");
        require(v.halted, "Not halted");
        v.halted = false;
        v.hwm = v.equity; // cool-down: peak resets to where we resumed
        emit Resumed(agent, v.equity);
    }

    // ----------------------------------------------------------------
    // Gate + views
    // ----------------------------------------------------------------

    function _drawdownBps(uint128 hwm, uint128 equity)
        internal
        pure
        returns (uint256)
    {
        if (hwm == 0 || equity >= hwm) return 0;
        // Ceiling division: round the loss UP so the killswitch is never lenient
        // at the budget boundary.
        return (uint256(hwm - equity) * BPS + uint256(hwm) - 1) / uint256(hwm);
    }

    /// @notice The pre-trade gate. Returns whether trading is allowed and the
    ///         current drawdown in bps.
    function canTrade(address agent)
        external
        view
        returns (bool ok, uint256 ddBps)
    {
        Vault storage v = vaults[agent];
        if (!v.registered) return (false, 0);
        ddBps = _drawdownBps(v.hwm, v.equity);
        if (globalPaused || v.halted) return (false, ddBps);
        ok = ddBps < maxDrawdownBps;
    }

    function drawdownBps(address agent) external view returns (uint256) {
        Vault storage v = vaults[agent];
        return _drawdownBps(v.hwm, v.equity);
    }

    function getVault(address agent) external view returns (
        uint256 hwm,
        uint256 equity,
        uint40 updatedAt,
        bool halted,
        bool registered
    ) {
        Vault storage v = vaults[agent];
        return (v.hwm, v.equity, v.updatedAt, v.halted, v.registered);
    }

    function getVaultCount() external view returns (uint256) {
        return vaultList.length;
    }
}
