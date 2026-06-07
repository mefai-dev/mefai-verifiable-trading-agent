// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title MEFAI Commit-Reveal Prediction Registry
 * @notice Verifiable prediction protocol. An agent COMMITS a keccak256 seal of a
 *         prediction before its outcome window, then REVEALS the plaintext later.
 *         The seal binds the prediction at commit time, so it cannot be backfit,
 *         cherry-picked, or front-run. An oracle grades the revealed prediction
 *         against realized price. Committed-but-unrevealed entries stay visible,
 *         so selective reveal (hiding losers) is itself provable.
 * @dev Agents commit and reveal with their own wallet (self-sovereign authorship).
 *      The oracle only grades outcomes; it cannot author or alter predictions.
 */
contract CommitRevealPredictionRegistry {
    address public owner;
    address public oracle;
    bool public paused;

    enum Signal { BUY, SELL, HOLD }
    enum Outcome { PENDING, TARGET_HIT, STOP_HIT, EXPIRED }

    struct Commitment {
        bytes32 seal;          // keccak256 of the sealed prediction + salt
        address agent;         // committer wallet (binds authorship)
        uint40 committedAt;
        uint40 expiresAt;      // outcome window close (binds the reveal window)
        uint40 revealDeadline; // reveal must land at or before this
        bool revealed;
    }

    struct Prediction {
        uint256 commitId;
        bytes32 agentId;
        string symbol;
        Signal signal;
        uint8 confidence;      // 0-100
        uint64 entryPrice;     // price * 1e4
        uint64 targetPrice;
        uint64 stopLoss;
        uint40 expiresAt;
        uint40 revealedAt;
        Outcome outcome;
        uint64 exitPrice;
    }

    struct Agent {
        string name;
        address wallet;
        uint32 committed;
        uint32 revealed;
        uint32 correct;
        uint32 wrong;
        int16 streak;
        int16 bestStreak;
        bool registered;
    }

    Commitment[] public commitments;
    Prediction[] public predictions;
    // commitId => predictionId + 1 (0 means not revealed)
    mapping(uint256 => uint256) public predictionOf;
    mapping(bytes32 => Agent) public agents;
    bytes32[] public agentIds;

    uint256 public totalCommitted;
    uint256 public totalRevealed;
    uint256 public totalVerified;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event OracleSet(address indexed oracle);
    event PausedSet(bool paused);
    event AgentRegistered(bytes32 indexed agentId, string name, address wallet);
    event Committed(
        uint256 indexed commitId,
        bytes32 indexed agentId,
        bytes32 seal,
        uint40 expiresAt,
        uint40 revealDeadline
    );
    event Revealed(
        uint256 indexed commitId,
        uint256 indexed predictionId,
        bytes32 indexed agentId,
        string symbol,
        Signal signal,
        uint64 entryPrice
    );
    event OutcomeVerified(
        uint256 indexed predictionId,
        bytes32 indexed agentId,
        Outcome outcome,
        uint64 exitPrice
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier onlyOracle() {
        require(msg.sender == oracle, "Not oracle");
        _;
    }

    modifier notPaused() {
        require(!paused, "Paused");
        _;
    }

    constructor() {
        owner = msg.sender;
        oracle = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
        emit OracleSet(msg.sender);
    }

    // ----------------------------------------------------------------
    // Admin
    // ----------------------------------------------------------------

    function setOracle(address _oracle) external onlyOwner {
        require(_oracle != address(0), "Zero address");
        oracle = _oracle;
        emit OracleSet(_oracle);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function setPaused(bool value) external onlyOwner {
        paused = value;
        emit PausedSet(value);
    }

    // ----------------------------------------------------------------
    // Agent registry
    // ----------------------------------------------------------------

    function registerAgent(string calldata name, address wallet)
        external
        onlyOracle
        returns (bytes32)
    {
        require(wallet != address(0), "Zero address");
        bytes32 id = keccak256(abi.encodePacked(name, wallet));
        require(!agents[id].registered, "Already registered");

        agents[id] = Agent({
            name: name,
            wallet: wallet,
            committed: 0,
            revealed: 0,
            correct: 0,
            wrong: 0,
            streak: 0,
            bestStreak: 0,
            registered: true
        });
        agentIds.push(id);

        emit AgentRegistered(id, name, wallet);
        return id;
    }

    // ----------------------------------------------------------------
    // Commit-reveal
    // ----------------------------------------------------------------

    /// @notice Canonical seal of a prediction. Compute off-chain with the same
    ///         fields and a private salt to produce the value passed to commit().
    function sealOf(
        bytes32 agentId,
        string calldata symbol,
        Signal signal,
        uint8 confidence,
        uint64 entryPrice,
        uint64 targetPrice,
        uint64 stopLoss,
        uint40 expiresAt,
        bytes32 salt
    ) public pure returns (bytes32) {
        return keccak256(
            abi.encode(
                agentId, symbol, signal, confidence,
                entryPrice, targetPrice, stopLoss, expiresAt, salt
            )
        );
    }

    /// @notice Commit a sealed prediction. Only the agent's own wallet may commit.
    ///         expiresAt is the outcome window close and must equal the expiresAt
    ///         sealed into the hash; revealDeadline must not outlive it, so a
    ///         reveal cannot be deferred past the outcome window.
    function commit(
        bytes32 agentId,
        bytes32 seal,
        uint40 expiresAt,
        uint40 revealDeadline
    ) external notPaused returns (uint256) {
        Agent storage a = agents[agentId];
        require(a.registered, "Agent not registered");
        require(msg.sender == a.wallet, "Not agent wallet");
        require(seal != bytes32(0), "Empty seal");
        require(expiresAt > block.timestamp, "Expiry in past");
        require(revealDeadline > block.timestamp, "Deadline in past");
        require(revealDeadline <= expiresAt, "Deadline after expiry");

        uint256 id = commitments.length;
        commitments.push(Commitment({
            seal: seal,
            agent: msg.sender,
            committedAt: uint40(block.timestamp),
            expiresAt: expiresAt,
            revealDeadline: revealDeadline,
            revealed: false
        }));

        a.committed++;
        totalCommitted++;

        emit Committed(id, agentId, seal, expiresAt, revealDeadline);
        return id;
    }

    /// @notice Reveal a previously committed prediction. The recomputed seal must
    ///         match the commitment, the caller must be the original committer,
    ///         and the reveal must land before the deadline.
    function reveal(
        uint256 commitId,
        bytes32 agentId,
        string calldata symbol,
        Signal signal,
        uint8 confidence,
        uint64 entryPrice,
        uint64 targetPrice,
        uint64 stopLoss,
        uint40 expiresAt,
        bytes32 salt
    ) external notPaused returns (uint256) {
        require(commitId < commitments.length, "Invalid commit ID");
        Commitment storage c = commitments[commitId];
        require(!c.revealed, "Already revealed");
        require(block.timestamp <= c.revealDeadline, "Reveal too late");
        require(msg.sender == c.agent, "Not committer");
        require(expiresAt == c.expiresAt, "Expiry mismatch");
        require(confidence <= 100, "Confidence 0-100");
        require(entryPrice > 0, "Invalid entry price");

        Agent storage a = agents[agentId];
        require(a.registered && a.wallet == c.agent, "Agent mismatch");

        bytes32 expected = sealOf(
            agentId, symbol, signal, confidence,
            entryPrice, targetPrice, stopLoss, expiresAt, salt
        );
        require(expected == c.seal, "Seal mismatch");

        c.revealed = true;

        uint256 pid = predictions.length;
        predictions.push(Prediction({
            commitId: commitId,
            agentId: agentId,
            symbol: symbol,
            signal: signal,
            confidence: confidence,
            entryPrice: entryPrice,
            targetPrice: targetPrice,
            stopLoss: stopLoss,
            expiresAt: expiresAt,
            revealedAt: uint40(block.timestamp),
            outcome: Outcome.PENDING,
            exitPrice: 0
        }));
        predictionOf[commitId] = pid + 1;

        a.revealed++;
        totalRevealed++;

        emit Revealed(commitId, pid, agentId, symbol, signal, entryPrice);
        return pid;
    }

    // ----------------------------------------------------------------
    // Outcome verification (oracle grades against realized price)
    // ----------------------------------------------------------------

    function verifyOutcome(uint256 predictionId, Outcome outcome, uint64 exitPrice)
        external
        onlyOracle
    {
        require(predictionId < predictions.length, "Invalid prediction ID");
        require(outcome != Outcome.PENDING, "Invalid outcome");
        Prediction storage p = predictions[predictionId];
        require(p.outcome == Outcome.PENDING, "Already verified");

        p.outcome = outcome;
        p.exitPrice = exitPrice;
        _applyOutcome(p.agentId, outcome);
        totalVerified++;

        emit OutcomeVerified(predictionId, p.agentId, outcome, exitPrice);
    }

    function verifyOutcomeBatch(
        uint256[] calldata predictionIds,
        Outcome[] calldata outcomes,
        uint64[] calldata exitPrices
    ) external onlyOracle {
        require(
            predictionIds.length == outcomes.length &&
            outcomes.length == exitPrices.length,
            "Array length mismatch"
        );
        for (uint256 i = 0; i < predictionIds.length; i++) {
            uint256 pid = predictionIds[i];
            require(pid < predictions.length, "Invalid prediction ID");
            Prediction storage p = predictions[pid];
            if (p.outcome != Outcome.PENDING) continue;
            Outcome outcome = outcomes[i];
            if (outcome == Outcome.PENDING) continue;

            p.outcome = outcome;
            p.exitPrice = exitPrices[i];
            _applyOutcome(p.agentId, outcome);
            totalVerified++;

            emit OutcomeVerified(pid, p.agentId, outcome, exitPrices[i]);
        }
    }

    function _applyOutcome(bytes32 agentId, Outcome outcome) internal {
        Agent storage a = agents[agentId];
        if (outcome == Outcome.TARGET_HIT) {
            a.correct++;
            if (a.streak < 0) {
                a.streak = 1;
            } else if (a.streak < type(int16).max) {
                a.streak += 1;
            }
            if (a.streak > a.bestStreak) a.bestStreak = a.streak;
        } else {
            a.wrong++;
            if (a.streak > 0) {
                a.streak = -1;
            } else if (a.streak > type(int16).min) {
                a.streak -= 1;
            }
        }
    }

    // ----------------------------------------------------------------
    // Views
    // ----------------------------------------------------------------

    function getCommitmentCount() external view returns (uint256) {
        return commitments.length;
    }

    function getPredictionCount() external view returns (uint256) {
        return predictions.length;
    }

    function getAgentCount() external view returns (uint256) {
        return agentIds.length;
    }

    function getAgentStats(bytes32 agentId) external view returns (
        string memory name,
        address wallet,
        uint32 committed,
        uint32 revealed,
        uint32 correct,
        uint32 wrong,
        int16 streak,
        int16 bestStreak
    ) {
        Agent storage a = agents[agentId];
        return (
            a.name, a.wallet, a.committed, a.revealed,
            a.correct, a.wrong, a.streak, a.bestStreak
        );
    }

    function getPrediction(uint256 predictionId) external view returns (
        uint256 commitId,
        bytes32 agentId,
        string memory symbol,
        Signal signal,
        uint8 confidence,
        uint64 entryPrice,
        uint64 targetPrice,
        uint64 stopLoss,
        uint40 expiresAt,
        uint40 revealedAt,
        Outcome outcome,
        uint64 exitPrice
    ) {
        require(predictionId < predictions.length, "Invalid ID");
        Prediction storage p = predictions[predictionId];
        return (
            p.commitId, p.agentId, p.symbol, p.signal, p.confidence,
            p.entryPrice, p.targetPrice, p.stopLoss, p.expiresAt,
            p.revealedAt, p.outcome, p.exitPrice
        );
    }

    function getArenaStats() external view returns (
        uint256 totalAgents,
        uint256 committed,
        uint256 revealed,
        uint256 verified,
        uint256 pendingReveals,
        uint256 pendingOutcomes
    ) {
        return (
            agentIds.length,
            totalCommitted,
            totalRevealed,
            totalVerified,
            totalCommitted - totalRevealed,
            totalRevealed - totalVerified
        );
    }
}
