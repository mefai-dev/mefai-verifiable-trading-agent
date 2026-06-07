import { expect } from "chai";
import { ethers } from "hardhat";

const SIGNAL_BUY = 0;
const OUT_PENDING = 0;
const OUT_TARGET = 1;
const OUT_STOP = 2;

async function deployRegistry() {
  const [owner, agent, oracle, stranger] = await ethers.getSigners();
  const Registry = await ethers.getContractFactory("CommitRevealPredictionRegistry");
  const reg = await Registry.deploy();
  await reg.waitForDeployment();
  return { reg, owner, agent, oracle, stranger };
}

function agentIdOf(name: string, wallet: string) {
  return ethers.keccak256(ethers.solidityPacked(["string", "address"], [name, wallet]));
}

const future = async (secs: number) =>
  (await ethers.provider.getBlock("latest"))!.timestamp + secs;

describe("CommitRevealPredictionRegistry", () => {
  it("commits, reveals on a matching seal, and grades the outcome", async () => {
    const { reg, agent } = await deployRegistry();
    const id = agentIdOf("LIVE", agent.address);
    await reg.registerAgent("LIVE", agent.address);

    const salt = ethers.hexlify(ethers.randomBytes(32));
    const exp = await future(7200);
    const fields = [id, "BTCUSDT", SIGNAL_BUY, 80, 700000000, 720000000, 690000000, exp, salt];
    const seal = await reg.sealOf(...(fields as any));
    const deadline = await future(3600);

    await expect(reg.connect(agent).commit(id, seal, exp, deadline))
      .to.emit(reg, "Committed");
    expect(await reg.totalCommitted()).to.equal(1n);

    await expect(reg.connect(agent).reveal(0, ...(fields as any)))
      .to.emit(reg, "Revealed");
    expect(await reg.totalRevealed()).to.equal(1n);

    // oracle (owner == oracle by default) grades it
    await expect(reg.verifyOutcome(0, OUT_TARGET, 720000000))
      .to.emit(reg, "OutcomeVerified");
    const stats = await reg.getAgentStats(id);
    expect(stats.correct).to.equal(1n);
    expect(stats.streak).to.equal(1n);
  });

  it("rejects a reveal whose fields do not match the seal", async () => {
    const { reg, agent } = await deployRegistry();
    const id = agentIdOf("LIVE", agent.address);
    await reg.registerAgent("LIVE", agent.address);
    const salt = ethers.hexlify(ethers.randomBytes(32));
    const exp = await future(7200);
    const seal = await reg.sealOf(id, "BTCUSDT", SIGNAL_BUY, 80, 700000000, 720000000, 690000000, exp, salt);
    await reg.connect(agent).commit(id, seal, exp, await future(3600));
    // tamper confidence 80 -> 95
    await expect(
      reg.connect(agent).reveal(0, id, "BTCUSDT", SIGNAL_BUY, 95, 700000000, 720000000, 690000000, exp, salt)
    ).to.be.revertedWith("Seal mismatch");
  });

  it("only the committer wallet may commit and reveal", async () => {
    const { reg, agent, stranger } = await deployRegistry();
    const id = agentIdOf("LIVE", agent.address);
    await reg.registerAgent("LIVE", agent.address);
    const seal = ethers.hexlify(ethers.randomBytes(32));
    await expect(
      reg.connect(stranger).commit(id, seal, await future(7200), await future(3600))
    ).to.be.revertedWith("Not agent wallet");
  });

  it("rejects a reveal after the deadline", async () => {
    const { reg, agent } = await deployRegistry();
    const id = agentIdOf("LIVE", agent.address);
    await reg.registerAgent("LIVE", agent.address);
    const salt = ethers.hexlify(ethers.randomBytes(32));
    const exp = await future(7200);
    const seal = await reg.sealOf(id, "BTCUSDT", SIGNAL_BUY, 80, 700000000, 720000000, 690000000, exp, salt);
    const deadline = await future(100);
    await reg.connect(agent).commit(id, seal, exp, deadline);
    await ethers.provider.send("evm_increaseTime", [200]);
    await ethers.provider.send("evm_mine", []);
    await expect(
      reg.connect(agent).reveal(0, id, "BTCUSDT", SIGNAL_BUY, 80, 700000000, 720000000, 690000000, exp, salt)
    ).to.be.revertedWith("Reveal too late");
  });

  it("only the oracle may grade outcomes and never twice", async () => {
    const { reg, agent, stranger } = await deployRegistry();
    const id = agentIdOf("LIVE", agent.address);
    await reg.registerAgent("LIVE", agent.address);
    const salt = ethers.hexlify(ethers.randomBytes(32));
    const exp = await future(7200);
    const fields = [id, "BTCUSDT", SIGNAL_BUY, 80, 700000000, 720000000, 690000000, exp, salt];
    const seal = await reg.sealOf(...(fields as any));
    await reg.connect(agent).commit(id, seal, exp, await future(3600));
    await reg.connect(agent).reveal(0, ...(fields as any));
    await expect(reg.connect(stranger).verifyOutcome(0, OUT_TARGET, 1)).to.be.revertedWith("Not oracle");
    await reg.verifyOutcome(0, OUT_STOP, 690000000);
    await expect(reg.verifyOutcome(0, OUT_TARGET, 1)).to.be.revertedWith("Already verified");
  });

  it("rejects a reveal deadline that outlives the outcome window", async () => {
    const { reg, agent } = await deployRegistry();
    const id = agentIdOf("LIVE", agent.address);
    await reg.registerAgent("LIVE", agent.address);
    const seal = ethers.hexlify(ethers.randomBytes(32));
    await expect(
      reg.connect(agent).commit(id, seal, await future(3600), await future(7200))
    ).to.be.revertedWith("Deadline after expiry");
  });

  it("rejects a reveal whose expiry does not match the commitment", async () => {
    const { reg, agent } = await deployRegistry();
    const id = agentIdOf("LIVE", agent.address);
    await reg.registerAgent("LIVE", agent.address);
    const salt = ethers.hexlify(ethers.randomBytes(32));
    const exp = await future(7200);
    const seal = await reg.sealOf(id, "BTCUSDT", SIGNAL_BUY, 80, 700000000, 720000000, 690000000, exp, salt);
    await reg.connect(agent).commit(id, seal, exp, await future(3600));
    const otherExp = exp + 10;
    await expect(
      reg.connect(agent).reveal(0, id, "BTCUSDT", SIGNAL_BUY, 80, 700000000, 720000000, 690000000, otherExp, salt)
    ).to.be.revertedWith("Expiry mismatch");
  });

  it("surfaces committed-but-unrevealed entries (selective reveal is provable)", async () => {
    const { reg, agent } = await deployRegistry();
    const id = agentIdOf("LIVE", agent.address);
    await reg.registerAgent("LIVE", agent.address);
    await reg.connect(agent).commit(id, ethers.hexlify(ethers.randomBytes(32)), await future(7200), await future(3600));
    await reg.connect(agent).commit(id, ethers.hexlify(ethers.randomBytes(32)), await future(7200), await future(3600));
    const s = await reg.getArenaStats();
    expect(s.committed).to.equal(2n);
    expect(s.revealed).to.equal(0n);
    expect(s.pendingReveals).to.equal(2n);
  });
});

describe("RiskGovernor", () => {
  async function deployGov(bps = 1500) {
    const [owner, agent, keeper, stranger] = await ethers.getSigners();
    const Gov = await ethers.getContractFactory("RiskGovernor");
    const gov = await Gov.deploy(bps);
    await gov.waitForDeployment();
    return { gov, owner, agent, keeper, stranger };
  }

  it("allows trading inside the drawdown budget", async () => {
    const { gov, agent } = await deployGov(1500);
    await gov.registerVault(agent.address, 1000);
    await gov.recordEquity(agent.address, 900); // 10% dd < 15%
    const [ok, dd] = await gov.canTrade(agent.address);
    expect(ok).to.equal(true);
    expect(dd).to.equal(1000n); // 1000 bps = 10%
  });

  it("halts when drawdown breaches the budget and blocks trading", async () => {
    const { gov, agent } = await deployGov(1500);
    await gov.registerVault(agent.address, 1000);
    await expect(gov.recordEquity(agent.address, 800)) // 20% dd >= 15%
      .to.emit(gov, "Halted");
    const [ok, dd] = await gov.canTrade(agent.address);
    expect(ok).to.equal(false);
    expect(dd).to.equal(2000n);
  });

  it("tracks the high-water mark across an up move", async () => {
    const { gov, agent } = await deployGov(1500);
    await gov.registerVault(agent.address, 1000);
    await gov.recordEquity(agent.address, 1200); // new hwm
    await gov.recordEquity(agent.address, 1100); // ~8.3% from 1200, still ok
    const [ok] = await gov.canTrade(agent.address);
    expect(ok).to.equal(true);
    const v = await gov.getVault(agent.address);
    expect(v.hwm).to.equal(1200n);
  });

  it("resumes from current equity after a halt", async () => {
    const { gov, agent } = await deployGov(1500);
    await gov.registerVault(agent.address, 1000);
    await gov.recordEquity(agent.address, 800); // halted
    await expect(gov.resume(agent.address)).to.emit(gov, "Resumed");
    const [ok] = await gov.canTrade(agent.address);
    expect(ok).to.equal(true);
    const v = await gov.getVault(agent.address);
    expect(v.hwm).to.equal(800n); // peak reset to resume point
  });

  it("enforces keeper-only equity writes and owner-only resume", async () => {
    const { gov, agent, stranger } = await deployGov(1500);
    await gov.registerVault(agent.address, 1000);
    await expect(gov.connect(stranger).recordEquity(agent.address, 900)).to.be.revertedWith("Not keeper");
    await gov.recordEquity(agent.address, 800);
    await expect(gov.connect(stranger).resume(agent.address)).to.be.revertedWith("Not owner");
  });

  it("global pause blocks all vaults", async () => {
    const { gov, agent } = await deployGov(1500);
    await gov.registerVault(agent.address, 1000);
    await gov.setGlobalPaused(true);
    const [ok] = await gov.canTrade(agent.address);
    expect(ok).to.equal(false);
  });

  it("unregistered vault cannot trade", async () => {
    const { gov, stranger } = await deployGov(1500);
    const [ok] = await gov.canTrade(stranger.address);
    expect(ok).to.equal(false);
  });
});
