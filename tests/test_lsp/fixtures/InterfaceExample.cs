namespace SampleProject;

/// <summary>
/// Interface demonstrating virtual dispatch that requires semantic analysis.
/// </summary>
public interface IProcessor
{
    void Process(string input);
    string GetResult();
}

/// <summary>
/// First implementation of IProcessor.
/// </summary>
public class FastProcessor : IProcessor
{
    private string _lastResult = string.Empty;

    public void Process(string input)
    {
        _lastResult = input.ToUpper();
    }

    public string GetResult() => _lastResult;
}

/// <summary>
/// Second implementation of IProcessor.
/// </summary>
public class SlowProcessor : IProcessor
{
    private string _lastResult = string.Empty;

    public void Process(string input)
    {
        // Simulate slow processing
        Thread.Sleep(100);
        _lastResult = input.ToLower();
    }

    public string GetResult() => _lastResult;
}

/// <summary>
/// Consumer that uses interface dispatch.
/// </summary>
public class ProcessorConsumer
{
    private readonly IProcessor _processor;

    public ProcessorConsumer(IProcessor processor)
    {
        _processor = processor;
    }

    /// <summary>
    /// This method calls IProcessor.Process which could dispatch to either
    /// FastProcessor.Process or SlowProcessor.Process depending on runtime type.
    /// Tree-sitter cannot capture this relationship.
    /// </summary>
    public void DoWork(string input)
    {
        // Interface dispatch - semantic analysis needed to find implementations
        _processor.Process(input);
        var result = _processor.GetResult();
        Console.WriteLine(result);
    }
}
