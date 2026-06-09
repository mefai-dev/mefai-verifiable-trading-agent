import { ethers, run } from "hardhat";

// Deploys the BNB Hack verifiable-protocol layer:
//   1. CommitRevealPredictionRegistry  (commit-reveal prediction record)
//   2. RiskGovernor                    (on-chain drawdown killswitch)
// Usage:
//   DEPLOYER_PRIVATE_KEY=0x... npx hardhat run scripts/deploy-bnbhack.ts --network bscTestnet
// After deploy, set MAX_DRAWDOWN_BPS (default 1500 = 15%) and AGENT_NAME/AGENT_WALLET
// to auto-register the live agent.

const MAX_DRAWDOWN_BPS = Number(process.env.MAX_DRAWDOWN_BPS || 1500);
const AGENT_NAME = process.env.AGENT_NAME || "";
const AGENT_WALLET = process.env.AGENT_WALLET || "";
const VERIFY = process.env.VERIFY === "1";

async function verify(address: string, args: unknown[]) {
  if (!VERIFY) return;
  try {
    await run("verify:verify", { address, constructorArguments: args });
    console.log("  verified:", address);
  } catch (e) {
    console.log("  verify skipped/failed:", (e as Error).message);
  }
}

async function main() {
  const [deployer] = await ethers.getSigners();
  const bal = await ethers.provider.getBalance(deployer.address);
  console.log("Deployer:", deployer.address);
  console.log("Balance:", ethers.formatEther(bal), "BNB");
  if (bal === 0n) {
    throw new Error("Deployer has zero balance; fund it before deploying");
  }

  // 1. CommitRevealPredictionRegistry
  const Registry = await ethers.getContractFactory("CommitRevealPredictionRegistry");
  const registry = await Registry.deploy();
  await registry.waitForDeployment();
  const registryAddr = await registry.getAddress();
  console.log("CommitRevealPredictionRegistry:", registryAddr);

  // 2. RiskGovernor
  const Governor = await ethers.getContractFactory("RiskGovernor");
  const governor = await Governor.deploy(MAX_DRAWDOWN_BPS);
  await governor.waitForDeployment();
  const governorAddr = await governor.getAddress();
  console.log("RiskGovernor:", governorAddr, `(maxDrawdownBps=${MAX_DRAWDOWN_BPS})`);

  // Optional: register the live agent + its risk vault
  if (AGENT_NAME && AGENT_WALLET) {
    const tx1 = await registry.registerAgent(AGENT_NAME, AGENT_WALLET);
    await tx1.wait();
    const agentId = ethers.keccak256(
      ethers.solidityPacked(["string", "address"], [AGENT_NAME, AGENT_WALLET])
    );
    console.log(`Agent registered: ${AGENT_NAME} -> ${agentId}`);
  }

  const net = await ethers.provider.getNetwork();
  const scan = net.chainId === 56n ? "https://bscscan.com" : "https://testnet.bscscan.com";
  console.log("\n--- DEPLOYMENT COMPLETE ---");
  console.log(`Chain: ${net.chainId}`);
  console.log(`CommitRevealPredictionRegistry: ${registryAddr}`);
  console.log(`RiskGovernor:                   ${governorAddr}`);
  console.log(`BscScan: ${scan}/address/${registryAddr}`);
  console.log(`BscScan: ${scan}/address/${governorAddr}`);

  await verify(registryAddr, []);
  await verify(governorAddr, [MAX_DRAWDOWN_BPS]);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
